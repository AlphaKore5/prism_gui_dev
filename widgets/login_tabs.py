"""
Prism GUI — "Open login tabs", the one way every screen does it
───────────────────────────────────────────────────────────────
The sidebar's Login tabs, Settings' Open login tabs and the setup wizard's
button all open the same sign-in tabs. Each used to call the engine on the UI
thread itself: the window froze while Chrome's profile was copied, and an
error went nowhere, so on a fresh Windows 10 install the button "didn't do
anything" (09-Oct-2026). They all come here now — the tabs open on a
LoginTabsWorker, and the person is always told what happened: the tabs
opened, there was nothing to open, or the real error.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

import core_bridge as CB
import i18n


def open_login_tabs(parent, agents: dict, on_opened=None) -> bool:
    """Start opening the sign-in tabs for `agents` ({category: tool}) in
    Prism's own Chrome profile. False when nothing was started — the person
    has been told why, or a press before this one is still opening them.
    `on_opened(n)` runs once Chrome has been asked for the n tabs."""
    title = i18n.t("Login tabs")
    if CB.default_work.enabled():
        # Only the tools a task works in the browser need a sign-in; pictures
        # and video run on the Prism plan.
        agents = CB.default_work.sign_in_picks(agents, CB.config.load())
    elif CB.ai_client.active():
        QMessageBox.information(parent, title, i18n.t(
            "There is nothing to sign in to. Prism's AI runs through your "
            "Prism plan, so no browser is opened."))
        return False
    if not agents:
        QMessageBox.information(parent, title, i18n.t(
            "No AI tools are picked yet — open Setup first."))
        return False
    urls = CB.login_tab_urls(agents)
    if not urls:
        QMessageBox.information(parent, title, i18n.t(
            "None of the tools you picked has a sign-in page to open."))
        return False
    ok, err = CB.automation_available()
    if not ok:
        QMessageBox.warning(parent, title, i18n.t(
            "Automation deps not available: {error}").format(error=err))
        return False
    running = getattr(parent, "_login_tabs_worker", None)
    if running is not None and running.isRunning():
        return False
    from workers import LoginTabsWorker
    from widgets.loader import LoadingDialog
    wait = LoadingDialog(title, i18n.t("Opening your sign-in tabs…"), False, parent)
    wait.show()
    worker = LoginTabsWorker(urls, parent)
    worker.done.connect(lambda *_: wait.close())
    worker.failed.connect(lambda *_: wait.close())
    parent._login_tabs_worker = worker
    if on_opened is not None:
        worker.done.connect(on_opened)
    worker.failed.connect(lambda why: QMessageBox.warning(parent, title, i18n.t(
        "Prism couldn't open the login tabs.\n\n{error}\n\nThe details are in "
        "Prism's log.").format(error=why)))
    worker.start()
    return True
