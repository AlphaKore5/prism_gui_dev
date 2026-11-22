"""Which build flavour this is: the add-ons it contains, fixed at build time.

`FLAVOUR` is baked in when a build is made, exactly like `channel.CHANNEL`. It
is never read from the environment, a config file or a server, so a customer
cannot turn a Sales build into an Engineering one. "complete" is today's
product (all ten add-ons) and the default: every existing customer keeps it.

STDLIB ONLY and no imports of Prism code: packaging/prism.spec imports this in
a bare interpreter to decide what to exclude.

Why the add-on KEYS are listed here as well as imported in addons/flavours/:
the imports are what PyInstaller follows, this table is what tests and the
spec check them against. addons/registry.py refuses to start if the two
disagree, so a flavour module cannot quietly gain or lose an add-on.
"""
from __future__ import annotations

FLAVOUR = "complete"         # "complete" | "studio" | "sales" | "engineering"

# add-on keys per flavour. Order does not matter here (registry sorts by
# manifest order). Feature keys are untouched: a licence still means the same.
ADDONS_BY_FLAVOUR: dict[str, tuple[str, ...]] = {
    "complete": ("inquiry", "boq", "gerber", "step", "bom", "email", "leads",
                 "whatsapp", "reel", "motion"),
    "studio": ("reel", "motion"),
    "sales": ("inquiry", "email", "leads", "whatsapp"),
    "engineering": ("boq", "bom", "step", "gerber"),
}

FLAVOURS = tuple(ADDONS_BY_FLAVOUR)


# What to call each add-on when telling someone their build does not have it
# (gate G6), and which routed agents belong to it (only Reel and Motion own
# any). The manifests of an absent add-on are not in the build, so this is the
# one place a build without them can still read the names. A test pins both
# against the manifests in the complete build.
ADDON_NAMES: dict[str, str] = {
    "inquiry": "Email inquiries", "boq": "BOQ", "gerber": "Gerber",
    "step": "STEP", "bom": "BOM", "email": "Email", "leads": "Leads",
    "whatsapp": "WhatsApp", "reel": "Reel / Studio", "motion": "Motion Graphics",
}
ADDON_AGENTS: dict[str, tuple[str, ...]] = {
    "reel": ("Prism Reel", "Prism Studio"),
    "motion": ("Prism Motion",),
}


def addon_for_agent(agent: str) -> str:
    """The add-on key that owns a routed agent, or ""."""
    for key, agents in ADDON_AGENTS.items():
        if agent in agents:
            return key
    return ""


def flavours_with(key: str) -> tuple[str, ...]:
    """The flavours whose builds contain add-on `key`."""
    return tuple(f for f, keys in ADDONS_BY_FLAVOUR.items() if key in keys)


# Words for the customer, matching entitlement_copy.py (engineering-steps
# branch, 4eab057): the edition that owns an add-on is named "Prism Studio",
# "Prism Sales" or "Prism Engineering". Derived from the table above.
EDITION_NAMES = {"studio": "Prism Studio", "sales": "Prism Sales",
                 "engineering": "Prism Engineering"}


def owner_edition_name(key: str) -> str:
    """Display name of the first edition (studio, sales, engineering) that
    contains add-on `key`, or ""."""
    for f, name in EDITION_NAMES.items():
        if key in ADDONS_BY_FLAVOUR[f]:
            return name
    return ""


def addon_keys(flavour: str | None = None) -> tuple[str, ...]:
    return ADDONS_BY_FLAVOUR[flavour or FLAVOUR]


def excluded_addon_keys(flavour: str | None = None) -> tuple[str, ...]:
    """Add-ons a build of this flavour must NOT contain (for prism.spec)."""
    keep = set(addon_keys(flavour))
    return tuple(k for k in ADDONS_BY_FLAVOUR["complete"] if k not in keep)


# Third-party packages a build carries only when one of the listed add-ons is
# in it (owner decisions 2026-11-21, DECISIONS item 2). The rest of the
# environment is bundled by every flavour. Chromium (playwright) stays for
# Studio and Engineering because Motion rendering and the BOQ PDF quotation
# need it; Sales has neither. Video encoding (imageio_ffmpeg) is Reel and
# Motion only. The Engineering-only stack is STEP (cadquery with its OCP, vtk,
# casadi, numba/llvmlite, nlopt), Gerber's gerbonara and BOQ's pdfplumber.
# shapely is NOT here although Gerber uses it: the OCR engine imports it in
# every build (see ALWAYS_BUNDLED).
PACKAGE_NEEDS: dict[str, tuple[str, ...]] = {
    "playwright": ("reel", "motion", "boq"),
    "imageio_ffmpeg": ("reel", "motion"),
    "cadquery": ("step",), "OCP": ("step",), "vtk": ("step",),
    "vtkmodules": ("step",), "casadi": ("step",), "llvmlite": ("step",),
    "numba": ("step",), "nlopt": ("step",),
    "gerbonara": ("gerber",),
    "pdfplumber": ("boq",),
}

# Kept by EVERY build, so no flavour may ever list them in PACKAGE_NEEDS (a test
# pins this). The first group is the owner's list: the shell's file viewer needs
# ezdxf, matplotlib and pypdfium2; numpy and PIL are hard dependencies of
# those; OCR, Google Drive and voice are shared features. `av` is here although
# the decision named it with the video libraries: `import faster_whisper` imports
# `av` unconditionally (faster_whisper/audio.py), so a build without it has no
# voice input. `shapely` is here for the same reason: rapidocr_onnxruntime and
# rapidocr import it unconditionally (ch_ppocr_det/utils.py), so Sales and
# Studio builds that dropped it failed the packaged-app self-test with
# "No module named 'shapely'" (CI run 45068377735). tests/test_spec_flavours.py
# holds RUNTIME_DEPENDENTS, the table that proves every exclusion safe.
ALWAYS_BUNDLED: tuple[str, ...] = (
    "ezdxf", "matplotlib", "pypdfium2", "numpy", "PIL",
    "rapidocr", "rapidocr_onnxruntime", "onnxruntime", "cv2",
    "googleapiclient", "google_auth_oauthlib",
    "faster_whisper", "ctranslate2", "av", "shapely",
)


def package_excludes(flavour: str | None = None) -> list[str]:
    """Third-party packages this build must not contain. EMPTY for "complete"
    (it holds every add-on, so every package has a user)."""
    keep = set(addon_keys(flavour))
    return [pkg for pkg, needs in PACKAGE_NEEDS.items()
            if not keep.intersection(needs)]


def bundles(package: str, flavour: str | None = None) -> bool:
    """Does a build of this flavour carry third-party package `package`?
    prism.spec asks before it collects the package's files."""
    return package not in package_excludes(flavour)


def spec_excludes(flavour: str | None = None) -> list[str]:
    """Extra `excludes` for packaging/prism.spec. EMPTY for "complete", so the
    complete build's exclusion list is byte-for-byte what it was before
    flavours (the other flavours' tiny selection modules just ride along)."""
    flavour = flavour or FLAVOUR
    if flavour == "complete":
        return []
    return ([f"addons.{k}" for k in excluded_addon_keys(flavour)]
            + [f"addons.flavours.{f}" for f in FLAVOURS if f != flavour]
            + package_excludes(flavour))


# Who each build says it is (gate G2). DATA ONLY: nothing reads this yet (not
# app_meta, build.py, updater.py or CI). `name` is the install folder and the
# archive stem (no spaces, like today's "Prism"), `display` what the person
# sees, `bundle_id` the macOS bundle / Linux .desktop id, `channel` the suffix
# on the update channel name. "complete" is today's product and MUST stay
# byte-for-byte what app_meta.py and updater.platform_tag() give (a test pins
# it): a client that sends no channel (1.6.10, 1.6.11) keeps being served the
# complete build and can never be handed a flavour's manifest. Never reuse a
# retired name.
IDENTITY: dict[str, dict[str, str]] = {
    "complete": {"name": "Prism", "display": "Prism",
                 "bundle_id": "in.alphakore.prism", "channel": ""},
    "studio": {"name": "Prism-Studio", "display": "Prism Studio",
               "bundle_id": "in.alphakore.prism.studio", "channel": "studio"},
    "sales": {"name": "Prism-Sales", "display": "Prism Sales",
              "bundle_id": "in.alphakore.prism.sales", "channel": "sales"},
    "engineering": {"name": "Prism-Engineering", "display": "Prism Engineering",
                    "bundle_id": "in.alphakore.prism.engineering",
                    "channel": "engineering"},
}


def identity(flavour: str | None = None) -> dict[str, str]:
    return IDENTITY[flavour or FLAVOUR]


def update_channel(platform_tag: str, flavour: str | None = None) -> str:
    """The update channel name for this flavour given the base `<os>-<arch>`
    tag (`updater.platform_tag()`): the tag itself for "complete", else the
    tag plus "-<channel>". Manifest `manifest.<this>.signed` and the asset tag
    `v<ver>-assets-<this>` follow from it."""
    suffix = identity(flavour)["channel"]
    return f"{platform_tag}-{suffix}" if suffix else platform_tag


# main.py's frozen self-test (PRISM_SELFTEST) proves each tool a build ships.
# A check that belongs to an add-on runs only in a build that contains that
# add-on (ANY of the keys listed). A check not listed here runs in every
# flavour. "complete" holds all ten add-ons, so it runs every check, in
# today's order. Checks of tools every build keeps (owner decision 2026-11-21:
# OCR, Google Drive, faster-whisper, pypdfium2, numpy, PIL, ezdxf, matplotlib)
# are deliberately not listed. The table is data so a test can list the checks per flavour.
SELFTEST_NEEDS: dict[str, tuple[str, ...]] = {
    "BOQ add-on (ezdxf)": ("boq",),
    "Reel add-on (Pillow + renderer)": ("reel",),
    # Owner decision 2026-11-21 (DECISIONS item 2): Chromium stays in Studio
    # and Engineering (BOQ's PDF export and Motion rendering), not in Sales.
    "Prism Studio browser (Chromium)": ("reel", "motion", "boq"),
    "Reel encoding (FFmpeg)": ("reel", "motion"),
    "Studio editor + Motion runtime files": ("reel", "motion"),
    "Motion Graphics available": ("motion",),
    "STEP available": ("step",),
    "Gerber available": ("gerber",),
    "dep:dns.resolver": ("inquiry", "email"),
    "dep:shapely": ("gerber",),
    "dep:gerbonara": ("gerber",),
    "dep:pdfplumber": ("boq",),
}


def selftest_runs(check: str, flavour: str | None = None) -> bool:
    """Does the self-test run `check` in this flavour?"""
    need = SELFTEST_NEEDS.get(check)
    return need is None or any(k in addon_keys(flavour) for k in need)
