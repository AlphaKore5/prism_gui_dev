"""The engineering flavour's add-ons. STATIC imports only (see addons/registry.py)."""
from addons.boq.addon import MANIFEST as _boq              # noqa: E402
from addons.bom.addon import MANIFEST as _bom              # noqa: E402
from addons.step.addon import MANIFEST as _step              # noqa: E402
from addons.gerber.addon import MANIFEST as _gerber              # noqa: E402

MANIFESTS = (_boq, _bom, _step, _gerber)
