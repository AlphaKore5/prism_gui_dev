"""The complete flavour's add-ons. STATIC imports only (see addons/registry.py)."""
from addons.inquiry.addon import MANIFEST as _inquiry              # noqa: E402
from addons.boq.addon import MANIFEST as _boq              # noqa: E402
from addons.gerber.addon import MANIFEST as _gerber              # noqa: E402
from addons.step.addon import MANIFEST as _step              # noqa: E402
from addons.bom.addon import MANIFEST as _bom              # noqa: E402
from addons.email.addon import MANIFEST as _email              # noqa: E402
from addons.leads.addon import MANIFEST as _leads              # noqa: E402
from addons.whatsapp.addon import MANIFEST as _whatsapp              # noqa: E402
from addons.reel.addon import MANIFEST as _reel              # noqa: E402
from addons.motion.addon import MANIFEST as _motion              # noqa: E402

MANIFESTS = (_inquiry, _boq, _gerber, _step, _bom, _email, _leads, _whatsapp, _reel, _motion)
