"""S3c: Home reads the inquiry register on every build (the folder is in the
shared ~/.prism config). A build without the Inquiry add-on must not read it
and must show no inquiry numbers; a build with it must behave as before.
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

import core_bridge as CB
import dashboard_data as DATA
from addons import registry


def _without_inquiry():
    kept = tuple(a for a in registry.REGISTRY if a.key != "inquiry")
    return mock.patch.multiple(registry, REGISTRY=kept,
                               _BY_KEY={a.key: a for a in kept})


@pytest.fixture
def cfg_with_register():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = {"inquiry": {"folder": tmp}}
        paths = CB.get_mailflow().Paths(tmp)
        reg = CB.get_register()
        row = reg.from_message({"message_id": "<a@b>", "thread_id": "t1",
                                "subject": "Pump quote", "from_addr": "x@y.com",
                                "from_name": "X", "date": "2026-11-20",
                                "body": "Need a quote"}, rows=[]) \
            if hasattr(reg, "from_message") else None
        assert row is not None
        reg.save([row], paths.register_csv)
        assert reg.load(paths.register_csv), "fixture register must be readable"
        yield cfg


def test_without_the_inquiry_addon_nothing_is_read_and_home_has_no_numbers(cfg_with_register):
    with _without_inquiry(), \
         mock.patch.object(CB.get_register(), "load",
                           side_effect=AssertionError("register read")) as load:
        assert DATA.register_rows(cfg_with_register) == []
        assert DATA.inquiry_stats(cfg_with_register) is None
        assert DATA.needs_you(cfg_with_register)["to_quote"] == 0
        load.assert_not_called()


def test_with_the_inquiry_addon_the_register_is_read_as_before(cfg_with_register):
    if registry.by_key("inquiry") is None:
        pytest.skip("this flavour has no Inquiry add-on (see the test above)")
    assert len(DATA.register_rows(cfg_with_register)) == 1
