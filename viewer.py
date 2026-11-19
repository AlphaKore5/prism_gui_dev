"""The one door for "show me this file": inside Prism, never the OS opener.

Widget-safe: this module imports no dialog at load time. Everything that used
to hand a produced or attached file to the operating system calls
`open_file(path, parent)` instead. The OS launcher survives in exactly one
place, paths.open_in_other_app, reached only from the viewer's secondary
"Open in another app" button.
"""
from __future__ import annotations

import os
import sys

_WEB = ("http", "https", "mailto", "tel")


def _parent(parent):
    if parent is not None:
        return parent
    try:
        from PySide6.QtWidgets import QApplication
        return QApplication.activeWindow()
    except Exception:                                   # noqa: BLE001
        return None


def open_file(path, parent=None) -> bool:
    """Show a file or folder in Prism's own viewer. False for an empty path."""
    if not isinstance(path, (str, bytes, os.PathLike)) or not path:
        return False
    from dialogs.preview_dialog import open_preview
    open_preview(os.path.normpath(os.fsdecode(path)), _parent(parent))
    return True


def open_link(url: str, parent=None) -> bool:
    """A clicked link in rendered text. Web addresses go to the browser, a
    local file goes to the viewer, everything else (javascript:, data:,
    custom schemes) is ignored."""
    from urllib.parse import unquote, urlparse
    url = (url or "").strip()
    scheme = urlparse(url).scheme.lower()
    if scheme in _WEB:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        return bool(QDesktopServices.openUrl(QUrl(url)))
    if scheme == "file":
        local = unquote(urlparse(url).path)
        if sys.platform.startswith("win") and local[:1] == "/" and local[2:3] == ":":
            local = local[1:]
        return open_file(local, parent)
    return False


def route_links(browser) -> None:
    """Make a QTextBrowser's clicked links go through open_link() instead of
    Qt's own openExternalLinks, which hands ANY scheme (file:// included) to
    the OS. Text from an AI or a customer's email can contain such a link."""
    browser.setOpenLinks(False)
    browser.setOpenExternalLinks(False)
    # A weak reference, not the browser itself: a slot that holds its own
    # sender makes a cycle only Python's garbage collector can free, at some
    # random later allocation, after Qt may already have deleted the widget.
    # test_chat_thread crashed on Windows (0xC0000005) inside such an
    # allocation in 2 of 7 CI runs after this function arrived (ISS-026).
    import weakref
    ref = weakref.ref(browser)
    browser.anchorClicked.connect(lambda url: open_link(url.toString(), ref()))
