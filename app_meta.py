"""Identity of the packaged app — one place, read by the build and the app.

The packaging scripts import this rather than hard-coding strings, so bumping
VERSION here renames every artifact and updates the About text at once.
"""
from __future__ import annotations

NAME = "Prism"
# Reverse-DNS id: macOS uses it for the bundle, Linux for the .desktop file.
BUNDLE_ID = "in.alphakore.prism"
VERSION = "1.6.10"
DESCRIPTION = "One task in, a whole pipeline of AI tools out."
PUBLISHER = "Alphakore"

# Where the "Download" button on the update banner sends people, and where a
# person downloads a newer Prism from manually. A fixed vendor address baked
# into the build — never a URL the licence server hands us, so nothing that
# can talk to the client can redirect it (updater.py). The GitHub Releases
# page always shows the newest build; the CI workflow publishes every tag
# there.
# TODO(alphakore): point at WEBSITE + "/prism/download" once that page exists.
DOWNLOAD_URL = "https://github.com/AlphaKore5/prism_gui/releases/latest"

# Shown on every licence screen — when a trial ends, when an add-on is locked,
# when activation fails. This is the only route a stuck customer has back to
# us, so it must be an address someone actually reads.
# Confirmed 2026-08-30 for the first client build.
SUPPORT_EMAIL = "contactus@alphakore.org"
SUPPORT_PHONE = "798476995"
# Who a customer is actually reaching — not surfaced everywhere SUPPORT_EMAIL
# is (most of those are a single compact line), but available for anywhere a
# named contact reads better than a bare address (e.g. a signed email, a
# license-issue notice).
SUPPORT_CONTACT = "Parth Soni — CTO, Alphakore"
WEBSITE = "https://alphakore.org"
