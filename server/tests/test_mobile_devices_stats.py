"""Per-phone device stats for the AI Control Center.

``MobileTelemetry.device`` holds a single sample, so with two phones connected
the dashboard showed whichever phone reported last — the phones' stats appeared
to flip or lag. The gateway now keeps one ``DeviceTelemetry`` record per
``client_id`` and exposes them as a list.
"""

from __future__ import annotations

import time

from server.systems.agent.mobile_gateway_agent import (
    MobileGatewayAgent,
    _DEVICE_RETENTION_S,
)

PHONE_A = "phone-aaa"
PHONE_B = "phone-bbb"

ONE_PLUS = {
    "model": "NE2215",
    "manufacturer": "OnePlus",
    "platform": "android",
    "os_version": "Android 15",
    "battery": 82,
    "charging": False,
    "cpu_percent": 14.0,
    "ram_percent": 41.0,
    "ram_used_gb": 4.5,
    "ram_total_gb": 10.95,
}

HONOR = {
    "model": "GFY-LX2",
    "manufacturer": "HONOR",
    "platform": "android",
    "os_version": "Android 14",
    "battery": 99,
    "charging": True,
    "cpu_percent": 7.0,
    "ram_percent": 64.0,
    "ram_used_gb": 2.3,
    "ram_total_gb": 3.68,
}


def _connected_phone(gw: MobileGatewayAgent, client_id: str) -> str:
    """Open a control channel and return its key."""
    return gw.on_client_connected(client_id)


def test_two_phones_keep_separate_stats():
    gw = MobileGatewayAgent()
    key_a = _connected_phone(gw, PHONE_A)
    key_b = _connected_phone(gw, PHONE_B)

    gw.record_device_metrics(ONE_PLUS, 1.0, key_a)
    gw.record_device_metrics(HONOR, 2.0, key_b)

    rows = {r["id"]: r for r in gw.devices()}
    assert set(rows) == {PHONE_A, PHONE_B}
    assert rows[PHONE_A]["metrics"]["model"] == "NE2215"
    assert rows[PHONE_A]["metrics"]["ram_total_gb"] == 10.95
    assert rows[PHONE_B]["metrics"]["model"] == "GFY-LX2"
    assert rows[PHONE_B]["metrics"]["battery"] == 99
    assert rows[PHONE_A]["connected"] is True
    assert rows[PHONE_B]["connected"] is True


def test_rows_are_labelled_and_sorted_by_recent_activity():
    gw = MobileGatewayAgent()
    key_a = _connected_phone(gw, PHONE_A)
    key_b = _connected_phone(gw, PHONE_B)

    gw.record_device_metrics(ONE_PLUS, 1.0, key_a)
    time.sleep(0.01)
    gw.record_device_metrics(HONOR, 2.0, key_b)

    rows = gw.devices()
    assert rows[0]["id"] == PHONE_B, "most recently active phone first"
    assert rows[0]["label"] == "HONOR GFY-LX2"
    assert rows[1]["label"] == "OnePlus NE2215"


def test_last_sample_is_still_exposed_for_backwards_compatibility():
    """The System Health tab's single-device panel still reads ``device``."""
    gw = MobileGatewayAgent()
    key_a = _connected_phone(gw, PHONE_A)

    gw.record_device_metrics(ONE_PLUS, 1.0, key_a)
    gw.record_device_metrics(HONOR, 2.0, key_a)

    snap = gw.snapshot()
    assert snap["device"]["model"] == "GFY-LX2"
    assert snap["devices"][0]["metrics"]["model"] == "GFY-LX2"


def test_disconnected_phone_keeps_stats_but_reports_not_connected():
    gw = MobileGatewayAgent()
    key_a = _connected_phone(gw, PHONE_A)
    gw.record_device_metrics(ONE_PLUS, 1.0, key_a)

    gw.on_client_disconnected(key_a)

    rows = gw.devices()
    assert len(rows) == 1, "a recent drop must not erase the phone's stats"
    assert rows[0]["connected"] is False
    assert rows[0]["channels"] == 0
    assert rows[0]["metrics"]["model"] == "NE2215"


def test_devices_are_attributed_per_channel_not_globally():
    """A frame from one phone must never overwrite the other phone's row."""
    gw = MobileGatewayAgent()
    key_a = _connected_phone(gw, PHONE_A)
    key_b = _connected_phone(gw, PHONE_B)

    for _ in range(3):
        gw.record_device_metrics(HONOR, 2.0, key_b)
    gw.record_device_metrics(ONE_PLUS, 1.0, key_a)

    rows = {r["id"]: r["metrics"] for r in gw.devices()}
    assert rows[PHONE_A]["model"] == "NE2215"
    assert rows[PHONE_B]["model"] == "GFY-LX2"


def test_stale_disconnected_rows_are_pruned():
    gw = MobileGatewayAgent()
    key_a = _connected_phone(gw, PHONE_A)
    gw.record_device_metrics(ONE_PLUS, 1.0, key_a)
    gw.on_client_disconnected(key_a)

    assert gw.devices() != [], "still inside the retention window"
    assert gw.devices(now=time.time() + _DEVICE_RETENTION_S + 1) == []
    assert gw.devices() == [], "pruned rows stay gone"


def test_connected_rows_are_never_pruned():
    gw = MobileGatewayAgent()
    key_a = _connected_phone(gw, PHONE_A)
    gw.record_device_metrics(ONE_PLUS, 1.0, key_a)

    rows = gw.devices(now=time.time() + _DEVICE_RETENTION_S * 10)
    assert len(rows) == 1 and rows[0]["connected"] is True


def test_metrics_without_a_client_key_do_not_create_a_phantom_device():
    gw = MobileGatewayAgent()
    gw.record_device_metrics(ONE_PLUS, 1.0)  # legacy call shape

    assert gw.devices() == []
    assert gw.snapshot()["device"]["model"] == "NE2215"


def test_system_health_exposes_the_device_list(monkeypatch):
    from server.systems import system_health

    gw = MobileGatewayAgent()
    key_a = _connected_phone(gw, PHONE_A)
    key_b = _connected_phone(gw, PHONE_B)
    gw.record_device_metrics(ONE_PLUS, 1.0, key_a)
    gw.record_device_metrics(HONOR, 2.0, key_b)

    monkeypatch.setattr(
        "server.systems.agent.mobile_gateway_agent.get_mobile_gateway",
        lambda: gw,
    )

    mobile = system_health._collect_mobile()
    assert mobile["clients"] == 2
    assert len(mobile["devices"]) == 2
    assert {d["metrics"]["model"] for d in mobile["devices"]} == {
        "NE2215",
        "GFY-LX2",
    }
