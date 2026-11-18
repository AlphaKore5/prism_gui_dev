"""Owner-test fixes (stage 19) item 7: one consent, a 'Sending to Prism AI' panel."""
from __future__ import annotations
import os, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
_HOME = tempfile.mkdtemp(prefix="prism-s19-7-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

from PySide6.QtGui import QImage                                  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget               # noqa: E402
_app = QApplication.instance() or QApplication([])

from widgets import send_to_ai as S                               # noqa: E402
import core_bridge as CB                                          # noqa: E402

from dialogs.send_consent import SendConsentDialog as D


def _png():
    p = os.path.join(tempfile.mkdtemp(), "sheet.png")
    img = QImage(60, 40, QImage.Format_RGB32)
    img.fill(0xFFFFFF)
    img.save(p)
    return p


class Consent(unittest.TestCase):
    def setUp(self):
        S.reset_session()
        self.png = _png()

    def test_first_send_asks_once_then_not_again_this_session(self):
        cfg = {}
        with mock.patch.object(D, "exec", return_value=D.Accepted) as ex:
            self.assertTrue(S.ask_consent(None, cfg, self.png))
            self.assertTrue(S.ask_consent(None, cfg, self.png))
        ex.assert_called_once()
        self.assertNotIn(S.CONSENT_KEY, cfg)       # not saved without the tick

    def test_cancel_sends_nothing_and_is_not_remembered(self):
        cfg = {}
        with mock.patch.object(D, "exec", return_value=D.Rejected) as ex:
            self.assertFalse(S.ask_consent(None, cfg, self.png))
            self.assertFalse(S.ask_consent(None, cfg, self.png))
        self.assertEqual(ex.call_count, 2)          # asked again: no was not a yes

    def test_dont_ask_again_is_saved_to_config_and_skips_the_question(self):
        cfg = {}
        real_exec = D.exec
        def tick_and_send(self_):
            self_.remember.setChecked(True)
            return D.Accepted
        with mock.patch.object(D, "exec", tick_and_send), \
             mock.patch.object(CB.config, "save") as save:
            self.assertTrue(S.ask_consent(None, cfg, self.png))
        self.assertTrue(cfg[S.CONSENT_KEY])
        save.assert_called_once_with(cfg)
        S.reset_session()                           # a new run of the app
        with mock.patch.object(D, "exec") as ex:
            self.assertTrue(S.ask_consent(None, cfg, self.png))
        ex.assert_not_called()

    def test_dialog_shows_name_size_and_the_two_buttons(self):
        d = D(self.png, "drawing")
        self.assertEqual(d.preview.name.text(), "sheet.png")
        self.assertTrue(d.preview.size.text())
        self.assertFalse(d.preview.thumb.pixmap().isNull())
        self.assertEqual(d.send_btn.text().strip(), "Send to Prism AI")
        self.assertEqual(d.cancel_btn.text().strip(), "Cancel")
        self.assertEqual(d.remember.text(), "Don't ask again")


class Panel(unittest.TestCase):
    def test_panel_shows_what_is_sent_and_moves_while_it_works(self):
        host = QWidget()
        host.resize(800, 600)
        host.show()
        p = S.SendingPanel(host, _png())
        p.show_over()
        self.assertTrue(p.isVisible())
        self.assertEqual((p.bar.minimum(), p.bar.maximum()), (0, 0))   # busy bar
        self.assertEqual(p.preview.name.text(), "sheet.png")
        self.assertIn("Reading", p.message.text())
        p.hide()


class StepShowsThePanelOnlyWhenAPictureGoes(unittest.TestCase):
    def test_step_ask_flow(self):
        from addons.step import dialog as SD
        import test_step_dialog as T
        dlg = T._dialog()
        m = T._fake_measured(dlg)
        host_visible = []
        with mock.patch.object(SD, "StepAskWorker") as W:
            W.return_value.attachments = [{"kind": "image"}]
            dlg._ask_worker = W.return_value
            dlg._show_sending(m)
            self.assertIsNotNone(dlg._sending)
            dlg._on_failed("boom")
            self.assertIsNone(dlg._sending)
            W.return_value.attachments = []
            dlg._show_sending(m)
            self.assertIsNone(getattr(dlg, "_sending", None))


if __name__ == "__main__":
    unittest.main()
