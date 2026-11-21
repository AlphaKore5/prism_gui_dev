"""The studio flavour's add-ons. STATIC imports only (see addons/registry.py)."""
from addons.reel.addon import MANIFEST as _reel              # noqa: E402
from addons.motion.addon import MANIFEST as _motion              # noqa: E402

MANIFESTS = (_reel, _motion)
