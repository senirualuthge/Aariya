"""Tests for server/systems/emotion/predictor.py — the LSTM emotion forecaster."""

import asyncio
import time

import pytest

torch = pytest.importorskip("torch")

from server.systems.emotion import predictor
from server.systems.emotion.predictor import (
    build_sequences,
    enrich_prediction,
    predict_from_history,
    predict_future_state,
    save_model,
    train_predictor,
)


def _make_history(n: int, trend: float = 0.0, start: float = -0.4) -> list:
    """Synthetic chronological emotion trajectory (valence ramps up)."""
    history = []
    for i in range(n):
        history.append({
            "valence": max(-1.0, min(1.0, start + trend * i + (i % 3) * 0.02)),
            "arousal": 0.5,
            "trust": 0.5 + 0.02 * i,
        })
    return history


@pytest.fixture(autouse=True)
def _clear_predictor_cache():
    predictor._predictor_cache.clear()
    predictor._predictor_mtimes.clear()
    yield
    predictor._predictor_cache.clear()
    predictor._predictor_mtimes.clear()


# ── encoding / sequence builder ───────────────────────────────────────────────

def test_encode_frame_defaults():
    assert predictor._encode_frame({}) == [0.0, 0.5, 0.5, 0.0, 0.0]


def test_build_sequences_windows_and_targets():
    recs = [{"valence": i / 10, "arousal": 0.5, "trust": 0.5} for i in range(15)]
    X, Y = build_sequences(recs, seq_len=8)
    assert X.shape == (7, 8, 5)
    assert Y.shape == (7, 2)
    # Y[i] is the frame immediately AFTER window i
    assert torch.allclose(Y[0], torch.tensor([recs[8]["valence"], 0.5]))


def test_build_sequences_insufficient_data():
    X, Y = build_sequences([{"valence": 0.1}], seq_len=8)
    assert X.numel() == 0 and Y.numel() == 0


# ── training / checkpoints ────────────────────────────────────────────────────

def test_train_predictor_requires_enough_data():
    assert train_predictor(_make_history(3), epochs=2, seq_len=8) is None


def test_save_load_roundtrip(tmp_path):
    model = train_predictor(_make_history(40, trend=0.05), epochs=5, seq_len=8)
    assert model is not None
    path = tmp_path / "model.pt"
    save_model(model, path)
    loaded = predictor.load_model(path)
    for p1, p2 in zip(model.parameters(), loaded.parameters()):  # type: ignore
        assert torch.allclose(p1, p2)


def test_training_loss_decreases():
    """A trending trajectory should be learnable — final loss < initial loss."""
    model = train_predictor(_make_history(60, trend=0.05), epochs=12, seq_len=8)
    assert model is not None
    X, Y = build_sequences(_make_history(60, trend=0.05), seq_len=8)
    model.eval()  # type: ignore
    with torch.no_grad():
        pred_cont, _ = model(X)  # type: ignore
        loss = torch.nn.functional.mse_loss(pred_cont, Y)
    # A trained model must meaningfully fit the trend (zigzag noise included).
    assert float(loss) < 0.2


# ── inference ─────────────────────────────────────────────────────────────────

def test_predict_future_state_sane_outputs():
    model = train_predictor(_make_history(40, trend=0.05), epochs=4, seq_len=8)
    out = predict_future_state(model, _make_history(10))  # type: ignore
    assert -1.0 <= out["future_valence"] <= 1.0
    assert 0.0 <= out["future_arousal"] <= 1.0
    assert len(out["state_logits"]) == 3
    assert len(out["state_probs"]) == 3
    assert 0.0 <= out["confidence"] <= 1.0
    assert {"future_valence", "future_arousal", "state_logits", "distress_risk",
            "escalation_risk", "velocity_valence", "confidence"} <= set(out)


def test_predict_future_state_short_and_empty_history():
    model = train_predictor(_make_history(30), epochs=2, seq_len=8)
    out = predict_future_state(model, [{"valence": 0.2, "arousal": 0.5}])  # type: ignore
    assert out["future_valence"] is not None
    empty = predict_future_state(model, [])  # type: ignore
    assert empty["future_valence"] == 0.0
    assert empty["confidence"] == 0.0


# ── wiring: enrich_prediction ─────────────────────────────────────────────────

def test_enrich_prediction_no_model_returns_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(predictor, "MODEL_PATH", tmp_path / "missing.pt")
    heuristic = {"distress_risk": False, "escalation_risk": False,
                 "confidence": 0.5, "predicted_valence": 0.1}
    assert enrich_prediction(heuristic, _make_history(10)) == heuristic
    # too little history → unchanged even with a model
    assert enrich_prediction(heuristic, [{"valence": 0.1}]) == heuristic


def test_enrich_prediction_with_model(tmp_path, monkeypatch):
    path = tmp_path / "model.pt"
    save_model(train_predictor(_make_history(40, trend=0.05), epochs=4, seq_len=8), path)  # type: ignore
    monkeypatch.setattr(predictor, "MODEL_PATH", path)

    heuristic = {"distress_risk": False, "escalation_risk": False,
                 "confidence": 0.2, "predicted_valence": 0.3}
    enriched = enrich_prediction(heuristic, _make_history(12))

    assert enriched["predictor"] == "lstm"
    assert "predicted_valence" in enriched
    assert isinstance(enriched["distress_risk"], bool)
    assert enriched["confidence"] >= 0.2  # LSTM confidence blended in


def test_predict_from_history_none_without_torch_or_model(tmp_path, monkeypatch):
    monkeypatch.setattr(predictor, "MODEL_PATH", tmp_path / "missing.pt")
    assert predict_from_history(_make_history(10)) is None


# ── corroboration rule (LSTM can't blindly upgrade risk) ──────────────────────

def _fake_forecast(monkeypatch, **overrides):
    base = {
        "future_valence": -0.3, "future_arousal": 0.5,
        "distress_risk": True, "escalation_risk": False,
        "velocity_valence": -0.1, "confidence": 0.9,
        "state_logits": [0.0, 0.0, 0.0], "state_probs": [1 / 3] * 3,
    }
    base.update(overrides)
    monkeypatch.setattr(predictor, "predict_from_history", lambda h: base)
    return base


def test_enrich_weak_lstm_signal_cannot_upgrade(monkeypatch):
    # LSTM flags distress but -0.3 is not strongly below the threshold and the
    # heuristic disagrees → no upgrade (prevents spurious proactive messages).
    _fake_forecast(monkeypatch)
    heuristic = {"distress_risk": False, "escalation_risk": False,
                 "confidence": 0.2, "predicted_valence": 0.3}
    out = predictor.enrich_prediction(heuristic, _make_history(10))
    assert out["distress_risk"] is False
    # LSTM values still flow through for the forecast itself.
    assert out["predicted_valence"] == -0.3
    assert out["confidence"] == 0.9


def test_enrich_strong_signal_can_upgrade(monkeypatch):
    _fake_forecast(monkeypatch, future_valence=-0.6, velocity_valence=-0.3,
                   escalation_risk=True)
    heuristic = {"distress_risk": False, "escalation_risk": False,
                 "confidence": 0.2, "predicted_valence": 0.0}
    out = predictor.enrich_prediction(heuristic, _make_history(10))
    assert out["distress_risk"] is True    # -0.6 < -0.40 (strong)
    assert out["escalation_risk"] is True  # -0.3 < -0.22 (strong)


def test_enrich_lstm_can_downgrade_heuristic(monkeypatch):
    _fake_forecast(monkeypatch, future_valence=0.2, distress_risk=False,
                   escalation_risk=False, velocity_valence=0.05)
    heuristic = {"distress_risk": True, "escalation_risk": True,
                 "confidence": 0.2, "predicted_valence": -0.3}
    out = predictor.enrich_prediction(heuristic, _make_history(10))
    assert out["distress_risk"] is False
    assert out["escalation_risk"] is False


# ── checkpoint cache invalidation ─────────────────────────────────────────────

def test_get_predictor_reloads_when_checkpoint_retrained(tmp_path):
    path = tmp_path / "model.pt"
    save_model(train_predictor(_make_history(40, trend=0.05), epochs=3, seq_len=8), path)  # type: ignore

    first = predictor.get_predictor(path)
    assert first is not None
    assert predictor.get_predictor(path) is first  # cached

    # Retrain with different data, resave, force a fresh mtime.
    save_model(train_predictor(_make_history(40, trend=-0.05), epochs=3, seq_len=8), path)  # type: ignore
    path.touch()
    second = predictor.get_predictor(path)
    assert second is not None
    assert second is not first  # stale cache invalidated by mtime change


# ── training from DB history ──────────────────────────────────────────────────

def test_train_from_db_and_get_snapshot_history(tmp_path, isolated_db):
    from server.autonomy.state import AutonomyStore

    store = AutonomyStore()
    for i in range(20):
        store.save_snapshot("user_default", valence=0.05 * i,
                            arousal=0.5, trust=0.5)

    history = store.get_snapshot_history(user_id="user_default")
    assert len(history) == 20
    assert history[0]["valence"] == 0.0
    assert history[-1]["valence"] == pytest.approx(0.95)

    out = tmp_path / "trained.pt"
    model = predictor.train_from_db(epochs=2, seq_len=8, out_path=out)
    assert model is not None
    assert out.exists()
    # The saved checkpoint is usable for inference.
    forecast = predict_future_state(model, history[-10:])
    assert "future_valence" in forecast


def test_train_from_db_not_enough_history(tmp_path, isolated_db, monkeypatch):
    from server.autonomy.state import AutonomyStore

    AutonomyStore()  # empty table
    out = tmp_path / "trained.pt"
    assert predictor.train_from_db(epochs=2, seq_len=8, out_path=out) is None
    assert not out.exists()


# ── self-updating training cadence (sidecar meta + should_retrain) ────────────

def test_read_training_meta_missing_file_defaults(tmp_path):
    meta = predictor.read_training_meta(tmp_path / "nope.pt")
    assert meta == {"trained_at": 0.0, "max_snapshot_id": 0,
                    "count": 0, "seed_count": 0}


def test_read_training_meta_corrupt_file_defaults(tmp_path):
    path = tmp_path / "m.pt"
    predictor._meta_path(path).write_text("{ not valid json")
    assert predictor.read_training_meta(path) == {
        "trained_at": 0.0, "max_snapshot_id": 0, "count": 0, "seed_count": 0,
    }


def test_should_retrain_self_heals_missing_checkpoint(tmp_path):
    path = tmp_path / "m.pt"
    predictor._write_training_meta(path, trained_at=time.time() - 3600,
                                   max_snapshot_id=100, count=100)
    # Checkpoint file deleted while meta survives → retrain now, no interval
    # wait, regardless of new-snapshot count.
    due, reason = predictor.should_retrain(101, min_interval_seconds=24 * 3600,
                                           min_new_snapshots=50, model_path=path)
    assert due is True
    assert "checkpoint missing" in reason


def test_train_from_db_writes_sidecar_meta(tmp_path, isolated_db):
    from server.autonomy.state import AutonomyStore

    store = AutonomyStore()
    for i in range(20):
        store.save_snapshot("user_default", valence=0.05 * i,
                            arousal=0.5, trust=0.5)
    out = tmp_path / "trained.pt"
    assert predictor.train_from_db(epochs=2, seq_len=8, out_path=out) is not None

    meta = predictor.read_training_meta(out)
    assert meta["max_snapshot_id"] == 20
    assert meta["count"] == 20
    assert meta["seed_count"] == 0
    assert meta["trained_at"] > 0


# ── sessions-table bootstrap seed ─────────────────────────────────────────────

def _seed_sessions(conn, n: int, start: float = -0.4, step: float = 0.05):
    """Insert n chronological sessions rows with avg_valence ramping up."""
    for i in range(n):
        conn.execute(
            "INSERT INTO sessions (id, user_id, start_time, avg_valence, avg_arousal) "
            "VALUES (?, 'user_default', ?, ?, 0.5)",
            (f"sess_{i:03d}", f"2026-01-{i % 28 + 1:02d} 10:00:00",
             start + step * i),
        )
    conn.commit()


def test_session_to_record_maps_and_drops():
    rec = predictor._session_to_record({"avg_valence": -0.3, "avg_arousal": 0.6})
    assert rec == {"valence": -0.3, "arousal": 0.6, "trust": 0.5}
    assert predictor._session_to_record({"avg_valence": -0.3, "avg_arousal": None}) is None
    assert predictor._session_to_record({"avg_valence": None, "avg_arousal": 0.6}) is None


def test_sessions_to_records_orders_and_drops_nulls():
    rows = [
        {"avg_valence": 0.1, "avg_arousal": 0.4},
        {"avg_valence": None, "avg_arousal": 0.4},   # dropped
        {"avg_valence": 0.3, "avg_arousal": None},   # dropped
        {"avg_valence": 0.5, "avg_arousal": 0.6},
    ]
    recs = predictor._sessions_to_records(rows)
    assert len(recs) == 2
    assert [r["valence"] for r in recs] == [0.1, 0.5]


def test_train_from_db_bootstraps_from_sessions_only(tmp_path, isolated_db):
    """No snapshots yet — sessions history alone bootstraps a checkpoint."""
    from server.db import get_db_connection

    conn = get_db_connection()
    _seed_sessions(conn, 15)
    conn.close()

    out = tmp_path / "bootstrapped.pt"
    model = predictor.train_from_db(epochs=2, seq_len=8, out_path=out)
    assert model is not None
    assert out.exists()
    meta = predictor.read_training_meta(out)
    assert meta["seed_count"] == 15
    assert meta["count"] == 15
    assert meta["max_snapshot_id"] == 0


def test_train_from_db_merges_sessions_and_snapshots(tmp_path, isolated_db):
    from server.autonomy.state import AutonomyStore
    from server.db import get_db_connection

    conn = get_db_connection()
    _seed_sessions(conn, 5)
    conn.close()
    store = AutonomyStore()
    for i in range(10):
        store.save_snapshot("user_default", valence=0.05 * i,
                            arousal=0.5, trust=0.5)

    out = tmp_path / "merged.pt"
    model = predictor.train_from_db(epochs=2, seq_len=8, out_path=out)
    assert model is not None
    meta = predictor.read_training_meta(out)
    assert meta["count"] == 15        # 5 sessions + 10 snapshots
    assert meta["seed_count"] == 5
    assert meta["max_snapshot_id"] == 10  # watermark from snapshots only


def test_train_from_db_sessions_only_insufficient(tmp_path, isolated_db):
    from server.db import get_db_connection

    conn = get_db_connection()
    _seed_sessions(conn, 3)
    conn.close()
    out = tmp_path / "x.pt"
    assert predictor.train_from_db(epochs=2, seq_len=8, out_path=out) is None
    assert not out.exists()


def test_should_retrain_never_trained_with_session_seed(tmp_path):
    path = tmp_path / "m.pt"
    # No snapshots, but real session history → bootstrap is due
    due, _ = predictor.should_retrain(0, min_new_snapshots=100,
                                      seed_records=120, model_path=path)
    assert due is True
    # Seed alone too small to matter
    due, reason = predictor.should_retrain(0, min_new_snapshots=100,
                                           seed_records=10, model_path=path)
    assert due is False
    assert "never trained" in reason
    # Snapshots + seed combined cross the threshold
    due, _ = predictor.should_retrain(95, min_new_snapshots=100,
                                      seed_records=10, model_path=path)
    assert due is True


def test_should_retrain_never_trained(tmp_path):
    path = tmp_path / "m.pt"  # no checkpoint / meta yet
    due, reason = predictor.should_retrain(150, min_new_snapshots=100,
                                           model_path=path)
    assert due is True
    due, reason = predictor.should_retrain(50, min_new_snapshots=100,
                                           model_path=path)
    assert due is False


def test_should_retrain_requires_new_snapshots(tmp_path):
    path = tmp_path / "m.pt"
    predictor._write_training_meta(path, trained_at=time.time() - 25 * 3600,
                                   max_snapshot_id=100, count=100)
    path.touch()  # checkpoint exists — exercises the new-snapshot gate
    # Interval elapsed + enough new snapshots → due
    due, _ = predictor.should_retrain(180, min_interval_seconds=24 * 3600,
                                      min_new_snapshots=50, model_path=path)
    assert due is True
    # Interval elapsed but only a few new records → not due
    due, reason = predictor.should_retrain(120, min_interval_seconds=24 * 3600,
                                           min_new_snapshots=50, model_path=path)
    assert due is False
    assert "new records" in reason


def test_should_retrain_interval_gate(tmp_path):
    path = tmp_path / "m.pt"
    predictor._write_training_meta(path, trained_at=time.time() - 3600,
                                   max_snapshot_id=100, count=100)
    path.touch()  # checkpoint exists — exercises the interval gate
    # Plenty of new snapshots, but only 1h since training → not due
    due, reason = predictor.should_retrain(500, min_interval_seconds=24 * 3600,
                                           min_new_snapshots=10, model_path=path)
    assert due is False
    assert "interval" in reason


def test_should_retrain_counts_new_sessions(tmp_path):
    """New sessions since the last training count toward the retrain gate, so
    a sessions-heavy deployment stays fresh even with sparse snapshots."""
    path = tmp_path / "m.pt"
    predictor._write_training_meta(path, trained_at=time.time() - 25 * 3600,
                                   max_snapshot_id=100, count=200, seed_count=10)
    path.touch()
    # 0 new snapshots, but 60 new sessions since last training → due
    due, _ = predictor.should_retrain(100, min_interval_seconds=24 * 3600,
                                      min_new_snapshots=50, seed_records=70,
                                      model_path=path)
    assert due is True
    # Too few new records overall → not due
    due, reason = predictor.should_retrain(100, min_interval_seconds=24 * 3600,
                                           min_new_snapshots=50, seed_records=30,
                                           model_path=path)
    assert due is False
    assert "new records" in reason


# ── telemetry (inner-world / dashboard health) ────────────────────────────────

def test_telemetry_untrained(tmp_path, monkeypatch):
    monkeypatch.setattr(predictor, "MODEL_PATH", tmp_path / "missing.pt")
    t = predictor.telemetry([])
    assert t["status"] == "untrained"
    assert t["predictor"] is None
    assert t["trained_at"] is None
    assert t["checkpoint_age_hours"] is None
    assert t["forecast"] is None
    assert t["corpus"] == {"snapshots": 0, "sessions": 0}


def test_telemetry_trained_with_forecast_and_age(tmp_path, monkeypatch):
    path = tmp_path / "m.pt"
    monkeypatch.setattr(predictor, "MODEL_PATH", path)
    save_model(train_predictor(_make_history(40, trend=0.05), epochs=3, seq_len=8), path)  # type: ignore
    predictor._write_training_meta(path, trained_at=time.time() - 3600,
                                   max_snapshot_id=12, count=12, seed_count=3)

    t = predictor.telemetry(_make_history(12), snapshots=12, sessions=3)
    assert t["status"] == "trained"
    assert t["predictor"] == "lstm"
    assert t["trained_at"] is not None
    assert t["checkpoint_age_hours"] == pytest.approx(1.0, abs=0.01)
    assert t["count"] == 12
    assert t["seed_count"] == 3
    assert t["corpus"] == {"snapshots": 12, "sessions": 3}
    assert t["forecast"] is not None and "future_valence" in t["forecast"]


def test_telemetry_corrupt_checkpoint_with_fresh_meta(tmp_path, monkeypatch):
    """Unreadable checkpoint but fresh meta → status untrained, age still shown."""
    path = tmp_path / "m.pt"
    monkeypatch.setattr(predictor, "MODEL_PATH", path)
    predictor._write_training_meta(path, trained_at=time.time() - 3600,
                                   max_snapshot_id=5, count=5, seed_count=0)
    path.write_text("not a torch checkpoint")
    t = predictor.telemetry(_make_history(10))
    assert t["status"] == "untrained"
    assert t["checkpoint_age_hours"] is not None
    assert t["forecast"] is None


def test_telemetry_trained_without_history(tmp_path, monkeypatch):
    path = tmp_path / "m.pt"
    monkeypatch.setattr(predictor, "MODEL_PATH", path)
    save_model(train_predictor(_make_history(30), epochs=2, seq_len=8), path)  # type: ignore
    t = predictor.telemetry([])
    assert t["status"] == "trained"   # model exists
    assert t["forecast"] is None      # but no history to run it on


# ── autonomy daemon wiring ────────────────────────────────────────────────────

def test_daemon_emotion_retrain_cadence(tmp_path, isolated_db, monkeypatch):
    """The daemon's retrain tick trains the model on accrued snapshots and
    broadcasts an `autonomy.model_trained` event (no manual CLI run)."""
    import server.autonomy.daemon as daemon_module
    from server.autonomy.daemon import AutonomyDaemon
    from server.autonomy.state import AutonomyStore

    monkeypatch.setattr(predictor, "MODEL_PATH", tmp_path / "model.pt")
    monkeypatch.setattr(daemon_module, "EMOTION_RETRAIN_MIN_NEW", 1)
    monkeypatch.setattr(daemon_module, "EMOTION_TRAIN_EPOCHS", 2)
    monkeypatch.setattr(daemon_module, "EMOTION_TRAIN_SEQ_LEN", 8)

    store = AutonomyStore()
    for i in range(20):
        store.save_snapshot("user_default", valence=0.05 * i,
                            arousal=0.5, trust=0.5)
    received = []

    async def broadcast(msg):
        received.append(msg)

    async def _flow():
        daemon = AutonomyDaemon(broadcast=broadcast)
        await daemon._emotion_retrain_tick()
        first = daemon._emotion_train_task
        assert first is not None
        await asyncio.wait_for(first, timeout=120)
        # Second call: interval not elapsed → no new training run is stacked.
        await daemon._emotion_retrain_tick()
        assert daemon._emotion_train_task is first
        return daemon

    daemon = asyncio.run(_flow())

    assert (tmp_path / "model.pt").exists()
    meta = predictor.read_training_meta(tmp_path / "model.pt")
    assert meta["max_snapshot_id"] == 20
    assert meta["trained_at"] > 0
    # The broadcast event carries fresh telemetry so dashboards update at once.
    trained_events = [m for m in received if m.get("type") == "autonomy.model_trained"]
    assert trained_events
    ev = trained_events[0]
    assert ev["predictor"]["status"] == "trained"
    assert ev["predictor"]["forecast"] is not None
    assert ev["predictor"]["corpus"]["snapshots"] == 20
    assert ev["snapshot_id"] == 20


def test_daemon_bootstraps_from_sessions(tmp_path, isolated_db, monkeypatch):
    """No snapshots yet — the daemon still trains from sessions history."""
    import server.autonomy.daemon as daemon_module
    from server.autonomy.daemon import AutonomyDaemon
    from server.db import get_db_connection

    monkeypatch.setattr(predictor, "MODEL_PATH", tmp_path / "model.pt")
    monkeypatch.setattr(daemon_module, "EMOTION_RETRAIN_MIN_NEW", 5)
    monkeypatch.setattr(daemon_module, "EMOTION_TRAIN_EPOCHS", 2)

    conn = get_db_connection()
    _seed_sessions(conn, 12)
    conn.close()
    received = []

    async def broadcast(msg):
        received.append(msg)

    async def _flow():
        daemon = AutonomyDaemon(broadcast=broadcast)
        await daemon._emotion_retrain_tick()
        task = daemon._emotion_train_task
        assert task is not None
        await asyncio.wait_for(task, timeout=120)

    asyncio.run(_flow())
    assert (tmp_path / "model.pt").exists()
    meta = predictor.read_training_meta(tmp_path / "model.pt")
    assert meta["seed_count"] == 12
    assert meta["max_snapshot_id"] == 0
    trained_events = [m for m in received if m.get("type") == "autonomy.model_trained"]
    assert trained_events
    ev = trained_events[0]
    assert ev["predictor"]["status"] == "trained"
    assert ev["predictor"]["forecast"] is None  # no snapshots to run it on
    assert ev["predictor"]["corpus"] == {"snapshots": 0, "sessions": 12}


def test_daemon_tick_wires_retrain_check(tmp_path, isolated_db, monkeypatch):
    """The main _tick cadence reaches the emotion retrain check."""
    import server.autonomy.daemon as daemon_module
    from server.autonomy.daemon import AutonomyDaemon
    from server.autonomy.state import AutonomyStore

    monkeypatch.setattr(predictor, "MODEL_PATH", tmp_path / "model.pt")
    monkeypatch.setattr(daemon_module, "EMOTION_RETRAIN_CHECK_SECONDS", 0)
    monkeypatch.setattr(daemon_module, "EMOTION_RETRAIN_MIN_NEW", 1)
    monkeypatch.setattr(daemon_module, "EMOTION_TRAIN_EPOCHS", 1)

    store = AutonomyStore()
    for i in range(15):
        store.save_snapshot("user_default", valence=0.05 * i,
                            arousal=0.5, trust=0.5)

    async def broadcast(msg):
        pass

    async def _flow():
        daemon = AutonomyDaemon(broadcast=broadcast)
        await daemon._tick()  # fires the retrain check (check cadence = 0)
        assert daemon._emotion_train_task is not None
        await asyncio.wait_for(daemon._emotion_train_task, timeout=120)
        return daemon

    daemon = asyncio.run(_flow())
    assert (tmp_path / "model.pt").exists()
    assert daemon._last_emotion_retrain_check > 0
