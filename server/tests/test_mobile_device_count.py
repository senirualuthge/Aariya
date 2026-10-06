"""Connected-device counting must be per DEVICE, not per socket.

The bug: the System Health tab reported "2 devices connected" for a single
phone. ``/ws/mobile`` (chat) and ``/ws/mobile/control`` (control) each bumped
the same counter, and one app install opens both — plus ``/ws/mobile/analytics``
— so the number tracked channels while the UI called them devices.

The fix: every channel announces a stable per-install ``client_id``, the
gateway refcounts channels per id, and ``connected_clients`` is the number of
distinct ids (with ``connected_channels`` still exposing the raw socket count).
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from server import main as server_main
from server.protocol import BrainState, MultimodalOutput
from server.systems.agent.mobile_analytics_agent import MobileAnalyticsAgent
from server.systems.agent.mobile_gateway_agent import (
    DeviceRegistry,
    MobileGatewayAgent,
)
from server.systems.system_health import _collect_mobile

PHONE_A = "phone-aaa"
PHONE_B = "phone-bbb"


def _counts(agent):
    snap = agent.snapshot()
    return snap["connected_clients"], snap["connected_channels"]


def test_one_phone_three_channels_is_one_device():
    """The reported bug: chat + control + analytics for a single phone."""
    gw = MobileGatewayAgent()
    an = MobileAnalyticsAgent()

    gw.on_client_connected(PHONE_A)   # /ws/mobile
    gw.on_client_connected(PHONE_A)   # /ws/mobile/control
    an.on_client_connected(PHONE_A)   # /ws/mobile/analytics

    assert _counts(gw) == (1, 2)
    assert _counts(an) == (1, 1)


def test_two_phones_count_separately():
    gw = MobileGatewayAgent()
    gw.on_client_connected(PHONE_A)
    gw.on_client_connected(PHONE_A)
    gw.on_client_connected(PHONE_B)

    assert _counts(gw) == (2, 3)


def test_device_leaves_only_when_its_last_channel_closes():
    gw = MobileGatewayAgent()
    chat = gw.on_client_connected(PHONE_A)
    control = gw.on_client_connected(PHONE_A)

    gw.on_client_disconnected(chat)
    assert _counts(gw) == (1, 1), "device stays while a channel remains"

    gw.on_client_disconnected(control)
    assert _counts(gw) == (0, 0)


def test_reconnect_does_not_double_count():
    """A dropped channel reopening on the same device must not add a device."""
    gw = MobileGatewayAgent()
    gw.on_client_disconnected(gw.on_client_connected(PHONE_A))
    gw.on_client_connected(PHONE_A)
    gw.on_client_connected(PHONE_A)

    assert _counts(gw) == (1, 2)


def test_peak_tracks_devices_not_channels():
    gw = MobileGatewayAgent()
    a_keys = [gw.on_client_connected(PHONE_A) for _ in range(3)]
    gw.on_client_connected(PHONE_B)          # two phones, four channels
    for key in a_keys:                       # phone A drops out entirely
        gw.on_client_disconnected(key)

    snap = gw.snapshot()
    assert snap["peak_clients"] == 2, "peak is a device count"
    assert snap["connected_clients"] == 1


def test_client_without_id_still_counts_each_socket():
    """Older app builds send no client_id — they must not silently vanish."""
    gw = MobileGatewayAgent()
    gw.on_client_connected()   # chat, unidentified
    gw.on_client_connected()   # control, unidentified

    assert _counts(gw) == (2, 2)


def test_unidentified_disconnect_never_drops_a_known_device():
    gw = MobileGatewayAgent()
    known = gw.on_client_connected(PHONE_A)
    gw.on_client_connected()               # unidentified socket
    gw.on_client_disconnected(None)        # legacy call site without a key

    assert _counts(gw) == (1, 1), "only the unidentified socket was released"

    # Proves the surviving entry is the identified device: releasing its own
    # key empties the registry. Had the known device been dropped instead,
    # this would be an unknown key and the count would stay at 1.
    gw.on_client_disconnected(known)
    assert _counts(gw) == (0, 0)


def test_unknown_key_disconnect_is_a_no_op():
    gw = MobileGatewayAgent()
    gw.on_client_connected(PHONE_A)
    gw.on_client_disconnected("phone-that-was-never-connected")

    assert _counts(gw) == (1, 1)


def test_registry_reuses_the_same_key_for_one_device():
    reg = DeviceRegistry("test")
    assert reg.connect(PHONE_A) == reg.connect(" phone-aaa ") == PHONE_A
    assert reg.connect() != reg.connect()
    assert reg.devices == 3 and reg.sockets == 4


def test_health_snapshot_reports_devices_not_channels():
    """What the GUI reads: system_health.mobile.clients must be the devices."""
    from server.systems.agent.mobile_gateway_agent import get_mobile_gateway

    gateway = get_mobile_gateway()
    before = gateway.snapshot()["connected_clients"]
    chat = gateway.on_client_connected(PHONE_A)
    control = gateway.on_client_connected(PHONE_A)
    try:
        mobile = _collect_mobile()
        assert mobile["clients"] == before + 1, "one phone → one device"
        assert mobile["connected_channels"] == gateway.snapshot()["connected_channels"]
        assert mobile["peak_clients"] >= 1
    finally:
        gateway.on_client_disconnected(control)
        gateway.on_client_disconnected(chat)

# ── Endpoint level: the exact pair of sockets the app opens ────────────────────

class _FakeBrain:
    """Deterministic brain double — the chat socket must not call an LLM."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self.state = BrainState(valence=0.4, arousal=0.7, emotion="calm")

    async def process(self, input_model, on_token=None):
        return MultimodalOutput(
            text="ok",
            expression="smile",
            gestures=[],
            thought=None,
            state_update=self.state,
        )

    def get_state(self) -> BrainState:
        return self.state


class _NoopDaemon:
    def start(self): pass

    async def stop(self): pass

    def on_user_message(self, *args, **kwargs): pass

    def record_snapshot(self, *args, **kwargs): pass


class _NoopWatcher:
    def start(self, loop): pass

    def stop(self): pass


@pytest.fixture
def hermetic_backend(monkeypatch, isolated_db):
    """Keep the app hermetic: no LLM, no daemon, no file watcher, test DB."""
    monkeypatch.setattr(server_main, "BrainV2", _FakeBrain)
    monkeypatch.setattr(server_main, "get_daemon", lambda *a, **k: _NoopDaemon())
    monkeypatch.setattr(server_main, "get_watcher", lambda *a, **k: _NoopWatcher())


def _fresh_gateway(monkeypatch) -> MobileGatewayAgent:
    """Point the app's lazy `get_mobile_gateway()` at a registry of our own, so
    assertions are exact and no other test's singleton state leaks in."""
    from server.systems.agent import mobile_gateway_agent as gw_module

    fresh = MobileGatewayAgent()
    monkeypatch.setattr(gw_module, "get_mobile_gateway", lambda: fresh)
    return fresh


def _await_counts(gateway: MobileGatewayAgent, devices: int, channels: int,
                  timeout: float = 5.0) -> None:
    """Wait for the registry to reach the expected state.

    WebSocket handlers run in the TestClient portal thread, so the accept that
    returns control to this thread and the increment that follows it are not
    ordered against each other — polling with a deadline asserts the eventual
    state without assuming the scheduler's timing.
    """
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = gateway.snapshot()
        if (last["connected_clients"], last["connected_channels"]) == (devices, channels):
            return
        time.sleep(0.02)
    pytest.fail(
        f"expected {devices} device(s)/{channels} channel(s) within {timeout}s, "
        f"last snapshot: clients={last and last['connected_clients']}, "
        f"channels={last and last['connected_channels']}"
    )


def test_app_chat_and_control_sockets_count_as_one_device(
    hermetic_backend, monkeypatch
):
    """The reported bug, end to end: one phone opens /ws/mobile AND
    /ws/mobile/control, and the gateway must still report ONE device."""
    gateway = _fresh_gateway(monkeypatch)

    with TestClient(server_main.app) as client:
        with client.websocket_connect(f"/ws/mobile?client_id={PHONE_A}"):
            with client.websocket_connect(
                f"/ws/mobile/control?client_id={PHONE_A}"
            ):
                _await_counts(gateway, devices=1, channels=2)

                # A genuinely second phone is a second device.
                with client.websocket_connect(f"/ws/mobile?client_id={PHONE_B}"):
                    _await_counts(gateway, devices=2, channels=3)

    # Every socket closed: both phones are gone, not stuck in the registry.
    _await_counts(gateway, devices=0, channels=0)


def test_phones_without_client_id_still_visible(hermetic_backend, monkeypatch):
    """An older app build sends no client_id — its sockets must still register
    (they cannot be grouped, but they must not disappear)."""
    gateway = _fresh_gateway(monkeypatch)

    with TestClient(server_main.app) as client:
        with client.websocket_connect("/ws/mobile"), \
             client.websocket_connect("/ws/mobile/control"):
            _await_counts(gateway, devices=2, channels=2)
