"""Where Prism puts the files it makes for the person: general artifacts, STEP
work, Gerber reports.

Each has a setting in config.json (an empty value means "the usual place"):

    artifacts_dir    generated files (Reel, images, documents)   engine: config.ARTIFACTS_DIR
    step_out_dir     STEP measurements and drawings              (already existed)
    gerber_out_dir   Gerber reports and cleaned layers

The usual places are on the Desktop ("Prism Artifacts", "Prism Step",
"Prism Gerber"), in the user's REAL home. A dev build keeps Prism's private
state in its own data folder, but a folder a person is meant to open must never
be hidden in it (RELEASE_ISSUES.md ISS-012), so dev builds default to the real
Desktop as well.

Qt-free on purpose: the Settings screen, the Gerber and STEP add-ons and the
tests all use it.
"""
from __future__ import annotations

import os

import channel
import paths

KINDS = ("artifacts", "step", "gerber")
KEY = {"artifacts": "artifacts_dir", "step": "step_out_dir", "gerber": "gerber_out_dir"}
FOLDER_NAME = {"artifacts": "Prism Artifacts", "step": "Prism Step", "gerber": "Prism Gerber"}


def usual_dir(kind: str) -> str:
    """The folder used when the person has chosen nothing."""
    return os.path.join(paths.desktop_dir(), FOLDER_NAME[kind])


def configured(cfg: dict | None, kind: str) -> str:
    """What the person chose, or "" for the usual place."""
    return str((cfg or {}).get(KEY[kind]) or "").strip()


def chosen(cfg: dict | None, kind: str, engine_default: str = "") -> str:
    """The folder to actually use for `kind`: the person's choice, else the
    engine's own default when there is one (an ordinary build keeps writing
    exactly where it always did), else the usual place."""
    mine = configured(cfg, kind)
    if mine:
        return os.path.abspath(os.path.expanduser(mine))
    if engine_default and not channel.is_dev():
        return engine_default
    return usual_dir(kind)


def check_folder(path: str) -> tuple[bool, str]:
    """Can Prism write here? Returns (ok, why not). Creates the folder: asking a
    person to choose one that does not exist yet is normal, and a folder that
    cannot be made is better found out now than in the middle of a run."""
    raw = (path or "").strip()
    if not raw:
        return True, ""                                   # empty = the usual place
    full = os.path.abspath(os.path.expanduser(raw))
    if os.path.splitdrive(full)[1] in ("", os.sep, "/", "\\"):
        return False, "That is the top of a drive. Choose a folder inside it."
    try:
        bundle = os.path.abspath(paths.bundle_dir())
    except Exception:                                      # noqa: BLE001
        bundle = ""
    if paths.is_frozen() and bundle and (full == bundle or full.startswith(bundle + os.sep)):
        return False, "That folder is inside Prism's own program files, which an update replaces."
    try:
        os.makedirs(full, exist_ok=True)
        probe = os.path.join(full, ".prism-write-test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as error:
        return False, f"Prism cannot write to that folder ({error.strerror or error})."
    return True, ""


def apply(cfg: dict | None, config_module=None) -> str:
    """Tell the engine where generated files go. Safe to call again whenever
    the setting changes. Returns the folder now in force for artifacts.

    The engine reads config.ARTIFACTS_DIR at call time and caches whether it
    could be written, so both are updated together."""
    if config_module is None:
        import core_bridge as CB
        config_module = CB.config
    target = chosen(cfg, "artifacts", getattr(config_module, "ARTIFACTS_DIR", ""))
    if target and target != getattr(config_module, "ARTIFACTS_DIR", ""):
        config_module.ARTIFACTS_DIR = target
        cache = getattr(config_module, "_root_cache", None)
        if isinstance(cache, dict):
            cache.update({"for": None, "root": None})
    return getattr(config_module, "ARTIFACTS_DIR", target)
