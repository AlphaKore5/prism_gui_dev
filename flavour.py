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
# casadi, numba/llvmlite, nlopt), Gerber (shapely, gerbonara) and BOQ's
# pdfplumber.
PACKAGE_NEEDS: dict[str, tuple[str, ...]] = {
    "playwright": ("reel", "motion", "boq"),
    "imageio_ffmpeg": ("reel", "motion"),
    "cadquery": ("step",), "OCP": ("step",), "vtk": ("step",),
    "vtkmodules": ("step",), "casadi": ("step",), "llvmlite": ("step",),
    "numba": ("step",), "nlopt": ("step",),
    "shapely": ("gerber",), "gerbonara": ("gerber",),
    "pdfplumber": ("boq",),
}

# Kept by EVERY build, so no flavour may ever list them in PACKAGE_NEEDS (a test
# pins this). The first group is the owner's list: the shell's file viewer needs
# ezdxf, matplotlib and pypdfium2; numpy and PIL are hard dependencies of
# those; OCR, Google Drive and voice are shared features. `av` is here although
# the decision named it with the video libraries: `import faster_whisper` imports
# `av` unconditionally (faster_whisper/audio.py), so a build without it has no
# voice input.
ALWAYS_BUNDLED: tuple[str, ...] = (
    "ezdxf", "matplotlib", "pypdfium2", "numpy", "PIL",
    "rapidocr", "rapidocr_onnxruntime", "onnxruntime", "cv2",
    "googleapiclient", "google_auth_oauthlib",
    "faster_whisper", "ctranslate2", "av",
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
