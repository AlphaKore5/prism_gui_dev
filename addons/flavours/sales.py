"""The sales flavour's add-ons. STATIC imports only (see addons/registry.py)."""
from addons.inquiry.addon import MANIFEST as _inquiry              # noqa: E402
from addons.email.addon import MANIFEST as _email              # noqa: E402
from addons.leads.addon import MANIFEST as _leads              # noqa: E402
from addons.whatsapp.addon import MANIFEST as _whatsapp              # noqa: E402

MANIFESTS = (_inquiry, _email, _leads, _whatsapp)
