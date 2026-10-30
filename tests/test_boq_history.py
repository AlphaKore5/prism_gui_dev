"""addons/boq/history.py -- item 30d's History screen: list the BOQ jobs
already saved by CB.config.save_run() (tagged "addon": "boq"), let a
person pick one by date, hand its saved state back.

Every test here points CB.config.RUNS_DIR at a throwaway temp directory
-- never the real ~/.prism/runs -- the same rule this project's own
conftest.py enforces for every other test.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication                         # noqa: E402

_app = QApplication.instance() or QApplication([])

import core_bridge as CB                                           # noqa: E402
from addons.boq import history as H                                # noqa: E402


class _TempRunsDir:
    """Points CB.config.RUNS_DIR at a fresh temp dir for one test, same
    isolation shape conftest.py's own CONFIG_PATH fixture uses."""

    def __enter__(self):
        self._tmp = tempfile.mkdtemp()
        self._patch = mock.patch.object(CB.config, "RUNS_DIR", self._tmp)
        self._patch.start()
        return self._tmp

    def __exit__(self, *exc):
        self._patch.stop()


def _write_run(runs_dir: str, name: str, record: dict, mtime: float | None = None):
    path = os.path.join(runs_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class ListBoqRunsFindsOnlyBoqTaggedRecordsNewestFirst(unittest.TestCase):
    def test_an_untagged_run_from_another_addon_is_excluded(self):
        with _TempRunsDir() as d:
            _write_run(d, "run_1.json", {"addon": "gerber", "query": "a Gerber job"})
            _write_run(d, "run_2.json", {"addon": "boq", "query": "a BOQ job"})
            out = H.list_boq_runs()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["query"], "a BOQ job")

    def test_newest_first_by_file_modified_time(self):
        with _TempRunsDir() as d:
            now = time.time()
            _write_run(d, "run_old.json", {"addon": "boq", "query": "older"}, now - 100)
            _write_run(d, "run_new.json", {"addon": "boq", "query": "newer"}, now)
            out = H.list_boq_runs()
        self.assertEqual([r["query"] for r in out], ["newer", "older"])

    def test_every_record_carries_its_own_file_path(self):
        with _TempRunsDir() as d:
            path = _write_run(d, "run_1.json", {"addon": "boq", "query": "x"})
            out = H.list_boq_runs()
        self.assertEqual(out[0]["_path"], path)

    def test_a_file_that_fails_to_parse_is_skipped_not_a_crash(self):
        with _TempRunsDir() as d:
            with open(os.path.join(d, "run_bad.json"), "w") as f:
                f.write("{not valid json")
            _write_run(d, "run_good.json", {"addon": "boq", "query": "fine"})
            out = H.list_boq_runs()   # must not raise
        self.assertEqual(len(out), 1)

    def test_no_boq_runs_at_all_is_just_an_empty_list(self):
        with _TempRunsDir():
            self.assertEqual(H.list_boq_runs(), [])


class BoqHistoryDialogShowsAndPicksARun(unittest.TestCase):
    def test_a_boq_run_appears_with_its_request_text(self):
        with _TempRunsDir() as d:
            _write_run(d, "run_1.json", {"addon": "boq", "request": "HVAC for floor 3"})
            dlg = H.BoqHistoryDialog()
        self.assertEqual(dlg.list.count(), 1)
        self.assertIn("HVAC for floor 3", dlg.list.item(0).text())

    def test_no_runs_shows_an_unselectable_placeholder_row(self):
        from PySide6.QtCore import Qt
        with _TempRunsDir():
            dlg = H.BoqHistoryDialog()
        self.assertEqual(dlg.list.count(), 1)
        item = dlg.list.item(0)
        self.assertFalse(item.flags() & Qt.ItemIsSelectable)

    def test_double_clicking_a_row_accepts_with_that_record_chosen(self):
        with _TempRunsDir() as d:
            _write_run(d, "run_1.json", {"addon": "boq", "request": "pick me"})
            dlg = H.BoqHistoryDialog()
            dlg.list.setCurrentRow(0)
            dlg._accept()
        self.assertEqual(dlg.chosen.get("request"), "pick me")
        self.assertEqual(dlg.result(), 1)   # QDialog.Accepted

    def test_the_open_button_starts_disabled_with_nothing_selected(self):
        with _TempRunsDir() as d:
            _write_run(d, "run_1.json", {"addon": "boq", "request": "x"})
            dlg = H.BoqHistoryDialog()
        self.assertFalse(dlg.open_btn.isEnabled())


class ResumeFromHistoryLoadsTheSavedStateOntoTheDialog(unittest.TestCase):
    """addons/boq/dialog.py's own BoqDialog._resume_from_history."""

    def _record(self, **over):
        base = {
            "_path": "/x/run_1.json",
            "request": "HVAC BOQ for floor 3",
            "query": "BOQ — HVAC BOQ for floor 3",
            "responses": {"format": ["1  Brick wall  12.00  m"]},
            "links": {"format": "https://example.com/chat"},
            "last_text": "1  Brick wall  12.00  m",
            "artifacts": "",
            "deliverable_path": "/x/boq.docx",
            "boq": {"quantities_csv": "/x/qty.csv", "source": "/x/site.dxf"},
        }
        base.update(over)
        return base

    def _dialog(self):
        from addons.boq.dialog import BoqDialog
        return BoqDialog({"api_key": "k"}, [], None, mode="boq")

    def test_the_last_answer_and_paths_are_restored(self):
        d = self._dialog()
        with mock.patch.object(d, "_offer_followup"):
            d._resume_from_history(self._record())
        self.assertEqual(d.result.toPlainText(), "1  Brick wall  12.00  m")
        self.assertEqual(d._deliverable_path, "/x/boq.docx")
        self.assertEqual(d.csv_path, "/x/qty.csv")
        self.assertEqual(d.cad_path, "/x/site.dxf")
        self.assertEqual(d.request, "HVAC BOQ for floor 3")

    def test_the_run_path_is_carried_so_a_followup_updates_the_same_record(self):
        d = self._dialog()
        with mock.patch.object(d, "_offer_followup"):
            d._resume_from_history(self._record(_path="/x/run_42.json"))
        self.assertEqual(d._boq_run_path, "/x/run_42.json")

    def test_a_followup_is_offered_when_there_is_an_answer_to_build_on(self):
        d = self._dialog()
        with mock.patch.object(d, "_offer_followup") as offer:
            d._resume_from_history(self._record())
        self.assertTrue(offer.called)

    def test_no_answer_in_the_record_does_not_offer_a_followup(self):
        d = self._dialog()
        with mock.patch.object(d, "_offer_followup") as offer:
            d._resume_from_history(self._record(last_text=""))
        self.assertFalse(offer.called)


if __name__ == "__main__":
    unittest.main()
