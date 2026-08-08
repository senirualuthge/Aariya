"""Tests for the WebRTC voice endpoint (server/realtime/webrtc_server.py).

Verifies the router is importable and that /offer negotiates a real SDP
answer from a client offer (no HTTP server, no network).
"""

import asyncio

import pytest

aiortc = pytest.importorskip("aiortc")

from fastapi.testclient import TestClient

from server.main import app


def _client_offer() -> dict:
    """Build a minimal client-side WebRTC offer SDP."""
    import aiortc as a

    async def _make():
        pc = a.RTCPeerConnection()
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        sdp = pc.localDescription.sdp
        await pc.close()
        return {"sdp": sdp, "type": "offer"}

    return asyncio.run(_make())


def test_webrtc_router_mounted():
    paths = []
    for r in app.routes:
        orig = getattr(r, "original_router", None)
        if orig is not None:
            paths.extend(getattr(route, "path", None) for route in orig.routes)
    assert "/offer" in paths
    assert "/interrupt" in paths


def test_interrupt_returns_ok():
    client = TestClient(app)
    resp = client.post("/interrupt")
    assert resp.status_code == 200
    assert resp.json() == {"status": "interrupted"}


def test_offer_answers_with_sdp():
    client = TestClient(app)
    resp = client.post("/offer", json=_client_offer())
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("type") == "answer"
    assert isinstance(body.get("sdp"), str) and len(body["sdp"]) > 10


def test_offer_rejects_missing_body():
    client = TestClient(app)
    resp = client.post("/offer", json={})
    assert resp.status_code == 422
