"""Tests for the /api/emotion/predictor status endpoint
(server/routers/emotion_predictor_router.py).

Runs the endpoint function directly (asyncio.run) against the isolated test
DB — no HTTP server, no network, and torch is present (importorskip).
"""

import asyncio

import pytest

torch = pytest.importorskip("torch")

from server.routers.emotion_predictor_router import predictor_status
from server.systems.emotion import predictor
from server.autonomy.state import AutonomyStore
from server.db import get_db_connection


@pytest.fixture(autouse=True)
def _clear_predictor_cache():
    predictor._predictor_cache.clear()
    predictor._predictor_mtimes.clear()
    yield
    predictor._predictor_cache.clear()
    predictor._predictor_mtimes.clear()


def _seed_snapshots(n: int, step: float = 0.05) -> None:
    store = AutonomyStore()
    for i in range(n):
        store.save_snapshot("user_default", valence=step * i,
                            arousal=0.5, trust=0.5)


def test_untrained_reports_status_and_null_forecast(tmp_path, isolated_db, monkeypatch):
    monkeypatch.setattr(predictor, "MODEL_PATH", tmp_path / "missing.pt")
    payload = asyncio.run(predictor_status())
    assert payload["status"] == "untrained"
    assert payload["predictor"] is None
    assert payload["forecast"] is None
    assert payload["meta"]["trained_at"] == 0.0
    assert payload["history_window"] == []
    assert payload["corpus"] == {"snapshots": 0, "sessions": 0}


def test_trained_with_history_returns_forecast(tmp_path, isolated_db, monkeypatch):
    monkeypatch.setattr(predictor, "MODEL_PATH", tmp_path / "model.pt")
    _seed_snapshots(20)
    predictor.train_from_db(epochs=2, seq_len=8, out_path=predictor.MODEL_PATH)

    payload = asyncio.run(predictor_status())
    assert payload["status"] == "trained"
    assert payload["predictor"] == "lstm"

    f = payload["forecast"]
    assert f is not None
    assert -1.0 <= f["future_valence"] <= 1.0
    assert 0.0 <= f["future_arousal"] <= 1.0
    assert isinstance(f["distress_risk"], bool)
    assert "confidence" in f and "state_probs" in f

    assert len(payload["history_window"]) == 20
    assert payload["window_used"] == 20
    assert payload["corpus"]["snapshots"] == 20
    assert payload["corpus"]["sessions"] == 0
    assert payload["meta"]["max_snapshot_id"] == 20
    assert payload["meta"]["seed_count"] == 0


def test_trained_without_history_has_null_forecast(tmp_path, isolated_db, monkeypatch):
    """A trained model with no recent snapshots → status trained, no forecast."""
    monkeypatch.setattr(predictor, "MODEL_PATH", tmp_path / "model.pt")
    # Sessions-only corpus (no snapshots → no forecast history window).
    conn = get_db_connection()
    for i in range(15):
        conn.execute(
            "INSERT INTO sessions (id, user_id, start_time, avg_valence, avg_arousal) "
            "VALUES (?, 'user_default', ?, ?, 0.5)",
            (f"sess_{i:03d}", f"2026-01-{i % 28 + 1:02d} 10:00:00", -0.4 + 0.05 * i),
        )
    conn.commit()
    conn.close()
    predictor.train_from_db(epochs=2, seq_len=8, out_path=predictor.MODEL_PATH)

    payload = asyncio.run(predictor_status())
    assert payload["status"] == "trained"   # model exists
    assert payload["forecast"] is None      # but no snapshots to run it on
    assert payload["history_window"] == []
    assert payload["corpus"]["sessions"] == 15
    assert payload["corpus"]["snapshots"] == 0
    assert payload["meta"]["seed_count"] == 15


def test_window_is_clamped(tmp_path, isolated_db, monkeypatch):
    monkeypatch.setattr(predictor, "MODEL_PATH", tmp_path / "model.pt")
    _seed_snapshots(10)
    predictor.train_from_db(epochs=2, seq_len=8, out_path=predictor.MODEL_PATH)

    # window=500 → clamped to MAX_WINDOW (200), but only 10 exist
    payload = asyncio.run(predictor_status(window=500))
    assert payload["window_used"] == 10

    # window=1 → clamped up to MIN_WINDOW (2)
    payload = asyncio.run(predictor_status(window=1))
    assert payload["window_used"] == 2
