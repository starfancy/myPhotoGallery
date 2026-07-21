from __future__ import annotations

import pytest

from myphoto.deps import _is_lan_ip


@pytest.mark.parametrize("ip", [
    "10.0.0.1",
    "192.168.1.1",
    "172.16.0.1",
    "127.0.0.1",
    "::1",
    "fc00::1",
])
def test_is_lan_ip_accepts_private(ip):
    assert _is_lan_ip(ip) is True


@pytest.mark.parametrize("ip", [
    "8.8.8.8",
    "203.0.113.1",
    "2001:db8::1",
    "unknown",
])
def test_is_lan_ip_rejects_public(ip):
    assert _is_lan_ip(ip) is False
