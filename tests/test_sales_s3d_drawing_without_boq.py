"""S3d: an inquiry with a drawing attached, in a build where nothing offers
MEASURE_DRAWING (Sales has no BOQ): the drawing stays on disk and listed, no
"Count quantities" button appears anywhere, and nothing opens a paywall.
Where BOQ is in the build (complete) the button is still there.
Run under PRISM_TEST_FLAVOUR=sales and complete."""
from __future__ import annotations

import os
import sys
import tempfile
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

_app = QApplication.instance() or QApplication([])

import core_bridge as CB
from core import mailflow, register
from addons import names, registry
from addons.inquiry import dialog as UI
from addons.inquiry import drawer as DRAWER


def _has_boq_offerer() -> bool:
    return registry.offering(names.MEASURE_DRAWING)[0] is not None


@pytest.fixture
def dialog(monkeypatch):
    monkeypatch.setattr(CB.config, "save", lambda cfg: None)
    folder = tempfile.mkdtemp()
    job = os.path.join(folder, "job1")
    os.makedirs(job)
    open(os.path.join(job, "plan.dxf"), "w").write("0\nEOF\n")
    r = register.blank_row()
    r.update({"Inquiry no": "INQ/26-27/0001", "Customer": "C1", "Email": "c@x.com",
              "Product asked": "Pump", "Quantity": "1", "Date received": "10-10-2026",
              "Status": "New", "Folder": job})
    register.save([r], mailflow.Paths(folder).register_csv)
    cfg = {"api_key": "", "inquiry": {"account": {}, "accounts": [], "folder": folder,
           "rate_list": "", "cost_sheet": "", "company": "A", "signature": "S",
           "terms": {"gst_percent": 18}, "followup_days": 2, "max_reminders": 3,
           "local_only": True, "auto_minutes": 0,
           "knowledge": {"own_domains": [], "customers": [], "vendors": [],
                         "learned": {}}, "state": {}}}
    d = UI.InquiryDialog(cfg)
    d.resize(1100, 800)
    d.show()
    d.show_view("pipeline")
    yield d, job
    d.close()


def _without_boq():
    kept = tuple(a for a in registry.REGISTRY if a.key not in ("boq",))
    return mock.patch.multiple(registry, REGISTRY=kept,
                               _BY_KEY={a.key: a for a in kept})


def test_no_boq_offerer_means_no_button_and_no_paywall(dialog):
    d, job = dialog
    row = d._register_rows[0]
    with _without_boq():
        assert not _has_boq_offerer()
        assert d._has_drawing(row) is False
        assert "boq" not in UI.actions_for("New", "register", d._has_drawing(row))
        assert "boq" not in UI.actions_for("Converted", "register", d._has_drawing(row))
        d._open_card(row["Inquiry no"])
        assert "boq" not in d.drawer.actions["secondary"]
        keys = {b.property("actionKey") for b in d.drawer.findChildren(QPushButton)}
        assert "boq" not in keys
        # the drawing is still there, only the promise is gone
        assert os.path.exists(os.path.join(job, "plan.dxf"))
        # reaching the old handler anyway: no message, no paywall, no dialog
        d._focus_row = row
        with mock.patch.object(UI.QMessageBox, "information", side_effect=AssertionError("modal")), \
             mock.patch.object(UI.QMessageBox, "exec", side_effect=AssertionError("modal")), \
             mock.patch.object(UI.QMessageBox, "warning", side_effect=AssertionError("modal")):
            d._make_boq()


def test_where_boq_is_in_the_build_the_button_is_still_offered(dialog):
    if not _has_boq_offerer():
        pytest.skip("this flavour has no BOQ add-on (see the test above)")
    d, _job = dialog
    row = d._register_rows[0]
    assert d._has_drawing(row) is True
    assert "boq" in UI.actions_for("New", "register", True)
    d._open_card(row["Inquiry no"])
    assert "boq" in d.drawer.actions["secondary"]
