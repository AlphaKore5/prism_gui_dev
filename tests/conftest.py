"""Shared test-harness state resets.

Two resets, one autouse fixture, and neither is behaviour: no test may see
`PRISM_LICENSE_OFFLINE_DEV`, and no test may hand the next one a licensing
thread that is still running.

1. The offline-dev hatch
────────────────────────
`licensing._offline_dev()` is a developer escape hatch. When the variable is
set and the build is not frozen, `licensing._unreachable_answer()` answers
"allowed" for anything the local token is entitled to, instead of refusing.
It is consulted *after* the network call has already raised `Unreachable`, so
it changes the ANSWER, never the round trip — it cannot make a hanging test
finish, and stripping it cannot make one hang.

That makes it ambient global state that silently rewrites a production
decision path, and the suite had no reset for it. Two ways it got set:

  · the operator exporting it on the command line (the documented invocation
    for this suite does exactly that), and
  · `tests/test_inquiry_screen.py` doing `os.environ.setdefault(...)` at
    module scope, which pytest executes during *collection* — so every other
    module ran with the hatch open even when the variable was unset in the
    environment. That line has been removed; this fixture is what stops the
    next one from mattering.

The victim was
`test_authorization.py::AuthorizeFlow::test_h_a_revoked_licence_gets_no_lease_and_loses_its_cache`,
which asserts that a revoked licence cannot fall back on its cached lease
once the server is unreachable. With the hatch open the fallback is granted,
and the revocation test fails — the one assertion that must never be
unreliable, because a genuine regression in it looks identical.

This is the same class of insulation `LeaseHarness.setUp` already applies to
`licensing.secretstore._keyring`: the answer a test gets must not depend on
what the developer has in their environment.

2. Licensing's fire-and-forget threads
──────────────────────────────────────
`licensing.refresh()` and `licensing.report_usage()` hand their work to a
daemon thread and return; nothing the customer does waits on one, which is
correct in the product and poison in a suite. Such a thread re-reads
`licensing.user_dir()` and `keys.public_keys()` at every step, and in tests
those are `mock.patch` globals belonging to whatever test is running *at that
instant* — not the one that started the thread.

What leaked: `test_authorization.py::LocalFirstStartup::
test_k_refresh_returns_immediately_and_never_raises` started one under a
patched `client._post` and let it outlive the patch. It reached the real
licence server, and its answer — a genuine signed token — was written by
`licensing._apply()` into the temp `~/.prism` of whichever test_gates.py test
had the floor eight modules later. Against test_gates' throwaway public key a
genuine token cannot verify, so the licence read TAMPERED, features went
empty, and every add-on padlocked.

Which tests it broke: `test_gates.py::WindowGates::
test_sidebar_padlocks_what_is_not_owned` and `::WindowGates::
test_owned_addon_still_blocked_when_the_server_is_unreachable`, roughly twice
in ten full runs and never in isolation.

That leak is fixed where it was made — the test now joins the thread inside
its patch. This drain is the net under the next one: a leaked thread that
survives its test gets waited for here, so a mistake costs a slow teardown
and a warning naming the test that made it, instead of a 2-in-10 failure in
somebody else's module.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import threading
import warnings

import pytest

# Qt needs a display and CI runners have none. Set BEFORE any test module is
# imported — conftest.py is the one file pytest guarantees it loads first, so
# this is the only place that works for the whole suite at once.
#
# Several GUI test modules already do this themselves, and that is exactly
# why it belongs here too: os.environ.setdefault at module scope only takes
# effect if that module happens to be the first one pytest imports. Alphabetical
# collection decided whether the suite ran headless — which is not a thing that
# should be decided by a filename.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_OFFLINE_DEV = "PRISM_LICENSE_OFFLINE_DEV"

# Long enough for a stub-answered thread to finish (microseconds) or a real
# one to time out against the server, short enough that a wedged thread does
# not read as a hung suite.
_THREAD_DRAIN_SECONDS = 10.0


# The licence fields that ARE the licence. `last_seen_utc` and
# `last_refresh_attempt` are heartbeat bookkeeping the app rewrites in normal
# use, so watching them would make this fixture fail on every clean run — and
# a guard that cries wolf is a guard somebody deletes. These five are the ones
# whose loss actually locks a customer out of software they paid for.
_LICENCE_FIELDS = ("token", "license_id", "key", "server", "designation")


def _real_home_files() -> dict[str, str]:
    """Fingerprint the developer's own ~/.prism — what a test must never
    touch: the licence's identity, and every saved run."""
    import json
    home = os.path.join(os.path.expanduser("~"), ".prism")
    out: dict[str, str] = {}
    licence = os.path.join(home, "license.json")
    if os.path.exists(licence):
        try:
            with open(licence, encoding="utf-8") as f:
                data = json.load(f)
            out["licence"] = hashlib.sha256(
                "|".join(str(data.get(k, "")) for k in _LICENCE_FIELDS)
                .encode("utf-8")).hexdigest()
        except (OSError, ValueError):
            out["licence"] = "unreadable"
    config = os.path.join(home, "config.json")
    if os.path.exists(config):
        # The Groq key, agent choices and mail settings live here. 2026-10-17:
        # a STEP test that reached config.save() overwrote them with its own
        # fixture (key "k") — nothing noticed, the next launch just said
        # "Groq rejected your API key".
        with open(config, "rb") as f:
            out["config"] = hashlib.sha256(f.read()).hexdigest()
    runs = os.path.join(home, "runs")
    if os.path.isdir(runs):
        out["runs/"] = ",".join(sorted(n for n in os.listdir(runs)
                                       if n.startswith("run_")))
    return out


def _real_token_still_verifies() -> bool:
    """Does the real ~/.prism token verify with the real keys for this
    device? Read with nothing patched — this runs after every test's
    patches are gone."""
    try:
        import json
        import licensing
        from licensing import device, keys, token
        home = os.path.join(os.path.expanduser("~"), ".prism")
        with open(os.path.join(home, "license.json"), encoding="utf-8") as f:
            data = json.load(f)
        device.reset_cache()
        token.verify(data.get("token") or "",
                     device_fp=device.fingerprint(home)[0],
                     public_keys=keys.public_keys())
        return True
    except Exception:                                   # noqa: BLE001
        return False


@pytest.fixture(scope="session", autouse=True)
def _the_suite_must_not_touch_the_real_home():
    """Fail loudly if a test writes to the developer's own ~/.prism.

    Not hypothetical, and not cheap to find by hand. Two real incidents:

      · A leaked licensing daemon thread (see below) reached the real server
        and wrote its genuine token into whatever `user_dir()` resolved to at
        that instant — sometimes the developer's actual licence file. The
        licence then read TAMPERED on the next real launch, with no clue why.
      · `tests/test_dashboard_data.py` passed `cfg["runs_dir"]` to
        `dashboard_data._run_files` and assumed that isolated it. It does not:
        that key is ignored and the folder is resolved through
        `workspace.runs_dir()`. The test deleted one REAL saved run per suite
        run, and its own "skip if empty" guard never fired — the list was
        non-empty precisely because it was full of the user's data. Fifty-two
        runs of history went that way before anyone noticed.

    Both were invisible until someone opened the app. This makes them a test
    failure instead: a session-scoped before/after fingerprint of the licence
    file and the set of saved runs.
    """
    before = _real_home_files()
    yield
    after = _real_home_files()
    if before == after:
        return
    lost = []
    if before.get("licence") != after.get("licence"):
        # A token that still verifies for THIS machine is the real server
        # refreshing the real licence — a network leak from some test whose
        # refresh thread outlived the drain (the renewal timeout is 45s
        # against a server that can take that long to wake). Nothing is
        # lost; the next launch reads VALID. Worth a warning naming it, not
        # a red suite. A token that does NOT verify is the original
        # incident — a test's fake key written into the real file — and
        # that stays a failure.
        if _real_token_still_verifies():
            warnings.warn(
                "a licensing refresh thread reached the real server during "
                "the suite and rotated the real ~/.prism token (it still "
                "verifies; the licence is fine). Some test started "
                "licensing.refresh() and did not join it.", stacklevel=1)
        else:
            lost.append("the real ~/.prism/license.json had its identity "
                        "rewritten (one of " + ", ".join(_LICENCE_FIELDS) + ")")
    if before.get("config") != after.get("config"):
        lost.append("the real ~/.prism/config.json was rewritten — a test "
                    "reached config.save() without isolating CONFIG_PATH")
    if before.get("runs/") != after.get("runs/"):
        was = set(filter(None, (before.get("runs/") or "").split(",")))
        now = set(filter(None, (after.get("runs/") or "").split(",")))
        gone, added = sorted(was - now), sorted(now - was)
        if gone:
            lost.append(f"{len(gone)} saved run(s) DELETED: {gone[:5]}")
        if added:
            lost.append(f"{len(added)} run(s) written into the real folder")
    if lost:
        raise AssertionError(
            "The suite wrote to the developer's own ~/.prism:\n  - "
            + "\n  - ".join(lost)
            + "\nA test must operate on a temp directory. Note that passing "
              "cfg['runs_dir'] does NOT isolate dashboard_data._run_files, and "
              "that a licensing daemon thread outliving its patch will write "
              "wherever user_dir() points when it finishes.")


@pytest.fixture(autouse=True)
def _config_is_never_the_real_one(tmp_path_factory, monkeypatch):
    """Every test saves its config into a throwaway file. `config.save()` is
    called from many dialogs (Generate, Settings, set-up…); a test that did not
    patch it wrote its fixture over the developer's real config.json — their
    Groq key, agent map and mail settings."""
    try:
        import core_bridge  # noqa: F401  (puts the engine on sys.path)
        from core import config
    except Exception:                                   # noqa: BLE001
        yield
        return
    cfg_dir = tmp_path_factory.mktemp("cfg")
    monkeypatch.setattr(config, "CONFIG_PATH", str(cfg_dir / "config.json"))
    # Not created: a fresh machine has no runs folder either, and code that
    # writes into it must make it (the first priced BOQ did not, and failed
    # only on CI, where the folder was absent).
    monkeypatch.setattr(config, "RUNS_DIR", str(cfg_dir / "runs"))
    yield


@pytest.fixture(autouse=True)
def _leads_run_direct_by_default(request, monkeypatch):
    """Leads & Outreach runs on the credit pool: every paid lookup goes to
    Prism's licence server, which holds the provider keys (prospector/gateway.py).
    The engine's own tests are about what the engine DOES with an answer, and
    they hand it a provider double directly — so they run in the developer's
    direct mode, PRISM_LEADS_DIRECT=1, which is what the engine did before the
    pool. A test about the pool marks itself `@pytest.mark.pooled` and gets the
    real default. Either way the gateway starts each test with no remembered
    balance, refusal or transport, so one test's out-of-credits cannot stop the
    next test's run."""
    if request.node.get_closest_marker("pooled"):
        monkeypatch.delenv("PRISM_LEADS_DIRECT", raising=False)
    else:
        monkeypatch.setenv("PRISM_LEADS_DIRECT", "1")
    from prospector import gateway
    gateway.forget()
    yield
    gateway.forget()


@pytest.fixture(autouse=True)
def _the_os_keyring_is_never_the_real_one(monkeypatch):
    """No test reads or writes the developer's real Keychain / Credential
    Manager / Secret Service. The licence key lives there, and the start-up
    path now re-activates silently with it, so a test that reached the real
    store could either overwrite the developer's key with a fixture or start
    a real activation. A test about the key passes its own backend by patching
    `secretstore._keyring`, as several already do."""
    from licensing import secretstore
    monkeypatch.setattr(secretstore, "_probed", True)
    monkeypatch.setattr(secretstore, "_backend", None)
    yield


@pytest.fixture(autouse=True)
def _isolate_ambient_state(request):
    """Close the offline-dev bypass for the duration of every test, then put
    the environment back exactly as it was; and let no licensing thread cross
    the finish line into the next test."""
    previous = os.environ.pop(_OFFLINE_DEV, None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ[_OFFLINE_DEV] = previous

        stragglers = [t for t in threading.enumerate()
                      if t.name.startswith("prism-") and t.is_alive()]
        for t in stragglers:
            t.join(_THREAD_DRAIN_SECONDS)
        still_running = [t.name for t in stragglers if t.is_alive()]
        if still_running:
            warnings.warn(
                f"{request.node.nodeid} left {still_running} running after "
                f"{_THREAD_DRAIN_SECONDS}s. It will read user_dir() and "
                f"public_keys() out of whichever test runs next, and write "
                f"where it is told. Join it in the test that starts it.",
                stacklevel=1)


class _NoServer:
    """A stand-in for a platform call that answers 'no server' at once, on the calling thread."""

    class _Sig:
        def __init__(self):
            self.fns = []

        def connect(self, fn):
            self.fns.append(fn)

    def __init__(self, route, data=None):
        self.route, self.data = route, dict(data or {})
        self.done, self.failed = self._Sig(), self._Sig()

    def start(self):
        for fn in list(self.failed.fns):
            fn("There is no server in a test.", {})


@pytest.fixture(autouse=True)
def _a_platform_call_never_reaches_the_network(monkeypatch):
    """The WhatsApp screens make their server calls through addons.whatsapp.ui.call. Left alone, a test that builds one of
    those screens would start a real worker thread that tries to reach the licence server — the same leak, from the same
    kind of thread, that section 2 above describes. So every such call is answered with an immediate "no server" failure;
    a test that wants real answers patches ui.PlatformWorker itself (tests/test_whatsapp_platform_ui.py does)."""
    try:
        from addons.whatsapp import ui
    except Exception:                                   # noqa: BLE001  (a test run without the GUI libraries)
        yield
        return
    monkeypatch.setattr(ui, "PlatformWorker", _NoServer)
    yield
