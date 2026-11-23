"""The suite may not reach the internet (tests/netguard.py, tests/conftest.py).

Every test here stays on this machine: the "connections" are refused by the guard
before a packet exists, or are a mocked low-level call.
"""
from __future__ import annotations

import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import netguard  # noqa: E402


def test_the_licence_server_is_this_machine_in_every_test():
    from licensing import client
    assert client.server_url().startswith("http://127.0.0.1")


def test_a_test_may_still_choose_its_own_server(monkeypatch):
    from licensing import client
    monkeypatch.setenv("PRISM_LICENSE_SERVER", "http://127.0.0.1:8123/")
    assert client.server_url() == "http://127.0.0.1:8123"


def test_an_unpatched_campaign_page_makes_no_real_call(monkeypatch):
    """campaigns_page imports PlatformWorker itself; it used to POST to the real
    licence server five times on activate."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from addons.whatsapp import campaigns_page, workers
    assert campaigns_page.PlatformWorker is workers.PlatformWorker      # the shared, unswapped class
    reached = []
    from addons.whatsapp import license_client
    monkeypatch.setattr(license_client, "platform", lambda *a, **k: reached.append(a) or {})
    page = campaigns_page.CampaignsPage({})
    page.activate()
    assert reached == []
    assert netguard.BLOCKED == []


def test_a_raw_connection_to_a_public_host_is_refused_naming_the_host():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(netguard.NetworkBlocked) as e:
            s.connect(("93.184.216.34", 443))
        assert "93.184.216.34" in str(e.value)
        assert "test_a_raw_connection_to_a_public_host" in str(e.value)
        with pytest.raises(netguard.NetworkBlocked):
            socket.getaddrinfo("prism-license-server.onrender.com", 443)
        with pytest.raises(netguard.NetworkBlocked):
            socket.create_connection(("example.com", 80), timeout=1)
    finally:
        s.close()
    assert [h for h, _ in netguard.BLOCKED][:1] == ["93.184.216.34"]
    netguard.forgive()                      # blocked on purpose: do not fail this test at teardown


def test_loopback_is_not_blocked():
    for host in ("127.0.0.1", "localhost", "::1", "127.0.0.2", b"localhost"):
        assert netguard.is_local(host)
    for host in ("8.8.8.8", "example.com", "prism-license-server.onrender.com", "10.0.0.5"):
        assert not netguard.is_local(host)


@pytest.mark.allow_network
def test_the_marker_lets_a_live_check_through_without_connecting(monkeypatch):
    seen = []
    monkeypatch.setattr(netguard, "_real_connect", lambda self, address: seen.append(address))
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect(("93.184.216.34", 443))
    finally:
        s.close()
    assert seen == [("93.184.216.34", 443)]
    assert netguard.BLOCKED == []
