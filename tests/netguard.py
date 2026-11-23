"""No test may reach a host outside this machine.

Installed once, for the whole session, by tests/conftest.py. It replaces four
Python-level entry points with versions that look at the host first:

    socket.getaddrinfo, socket.gethostbyname(_ex), socket.socket.connect(_ex)

Loopback (127.0.0.0/8, ::1, "localhost") and the unspecified address pass
through untouched, as do Unix-domain sockets, so the suite's own local test
servers still work. Anything else raises NetworkBlocked (an OSError, so the
product code's own "no network" handling runs exactly as on an aeroplane) and
is recorded; the autouse fixture in conftest.py then FAILS the test at teardown
naming the host, so a product `except Exception` that swallows the error cannot
hide a leak.

A deliberate live check opts out with @pytest.mark.allow_network, and must skip
itself when it has no credentials.

Windows: nothing here is POSIX-specific. It is pure Python on top of the socket
module's public names (no fork, signals, /proc or fcntl), `ipaddress` does the
address parsing, and requests/urllib3/imaplib/smtplib/ssl all reach the wire
through socket.getaddrinfo and socket.socket.connect on every platform. What it
cannot see: Qt's own network stack (QNetworkAccessManager, QWebEngine) and
anything run in a child process; neither is used by these tests today.
"""
from __future__ import annotations

import ipaddress
import socket

_LOCAL_NAMES = {"", "localhost", "localhost.localdomain"}


class NetworkBlocked(OSError):
    """A test tried to reach a host outside this machine."""


BLOCKED: list[tuple[str, str]] = []          # (host, kind) since the current test began
_state = {"allowed": False, "test": ""}

_real_getaddrinfo = socket.getaddrinfo
_real_gethostbyname = socket.gethostbyname
_real_gethostbyname_ex = socket.gethostbyname_ex
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_installed = False


def is_local(host) -> bool:
    if host is None:
        return True
    if isinstance(host, (bytes, bytearray)):
        host = bytes(host).decode("ascii", "replace")
    host = str(host).strip().strip("[]").split("%", 1)[0].lower()
    if host in _LOCAL_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_unspecified


def _refuse(host, kind):
    BLOCKED.append((str(host), kind))
    raise NetworkBlocked(
        "Prism's test suite may not reach the network: %s of %r by %s. Mock the call, "
        "or mark a deliberate live check @pytest.mark.allow_network."
        % (kind, host, _state["test"] or "no test (collection)"))


def _addr_host(address):
    if isinstance(address, tuple) and address:
        return address[0]
    return None


def _getaddrinfo(host, *a, **k):
    if not _state["allowed"] and not is_local(host):
        _refuse(host, "name lookup")
    return _real_getaddrinfo(host, *a, **k)


def _gethostbyname(host):
    if not _state["allowed"] and not is_local(host):
        _refuse(host, "name lookup")
    return _real_gethostbyname(host)


def _gethostbyname_ex(host):
    if not _state["allowed"] and not is_local(host):
        _refuse(host, "name lookup")
    return _real_gethostbyname_ex(host)


def _is_ip_socket(sock) -> bool:
    return sock.family in (socket.AF_INET, socket.AF_INET6)


def _connect(self, address):
    if not _state["allowed"] and _is_ip_socket(self) and not is_local(_addr_host(address)):
        _refuse(_addr_host(address), "connection")
    return _real_connect(self, address)


def _connect_ex(self, address):
    if not _state["allowed"] and _is_ip_socket(self) and not is_local(_addr_host(address)):
        _refuse(_addr_host(address), "connection")
    return _real_connect_ex(self, address)


def install() -> None:
    global _installed
    if _installed:
        return
    socket.getaddrinfo = _getaddrinfo
    socket.gethostbyname = _gethostbyname
    socket.gethostbyname_ex = _gethostbyname_ex
    socket.socket.connect = _connect
    socket.socket.connect_ex = _connect_ex
    _installed = True


def begin_test(nodeid: str, allowed: bool) -> None:
    BLOCKED.clear()
    _state["test"] = nodeid
    _state["allowed"] = allowed


def end_test() -> list[tuple[str, str]]:
    _state["allowed"] = False
    _state["test"] = ""
    return list(BLOCKED)


def forgive() -> None:
    """For the guard's own tests, which block on purpose."""
    BLOCKED.clear()
