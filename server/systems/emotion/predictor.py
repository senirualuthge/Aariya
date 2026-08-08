"""
EmotionPredictor — PyTorch LSTM forecasting of the user's emotional trajectory.
───────────────────────────────────────────────────────────────────────────────
Models how the user's emotional state evolves so Aariya can be warned of
impending frustration / valence drops BEFORE they happen.

Pipeline:
  1. train_from_db()        — pull session history (sessions table: coarse
                              per-session avg_valence/avg_arousal seed) plus
                              autonomy_snapshots, build sliding windows, train
                              the LSTM, save a checkpoint.
  2. predict_future_state() — run a trained model over a recent history window
                              (real inference — the old stub mapping is gone).
  3. enrich_prediction()    — upgrade the autonomy daemon's heuristic prediction
                              dict with LSTM forecasts when a model exists;
                              callers fall back silently otherwise.

The module imports torch lazily at module load with a guarded fallback so the
server never crashes when torch is absent (the predictor simply reports
"no model"). Checkpoints default to data/emotion_predictor.pt
(AARIYA_EMOTION_MODEL_PATH).

CLI:  python -m server.systems.emotion.predictor  [--epochs 30 --seq-len 8 ...]
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("aariya.emotion.predictor")

# ── Torch availability (guarded so imports never crash without torch) ────────
try:
    import torch
    import torch.nn as nn

    _TORCH_AVAILABLE = True
    # Pin torch to a single thread: it otherwise competes for OpenMP pools with
    # other in-process ML libs (chromadb, sentence-transformers) and can crash
    # with intermittent segmentation faults on model construction.
    torch.set_num_threads(1)
    try:
        torch.set_num_interop_threads(1)  # raises if already initialized
    except RuntimeError:
        pass
except ImportError:  # pragma: no cover — torch is a declared dependency
    torch = None
    nn = None
    _TORCH_AVAILABLE = False

# Thresholds aligned with server/systems/proactive/engine.py so a fired
# distress/escalation trigger is consistent across the pipeline.
DISTRESS_THRESHOLD = -0.25   # predicted valence below this = distress risk
ESCALATION_VELOCITY = -0.12  # valence dropping this fast per turn = escalation

# Feature layout — the 5-D encoding used at BOTH train and inference time:
# [valence, arousal, trust, contradiction, word_count]
INPUT_DIM = 5
NUM_CLASSES = 3   # discrete mood classes derived from future valence (aux loss)

# Where the trained checkpoint lives (env-overridable, mirrors data/brain_v4.db).
MODEL_PATH = Path(os.getenv("AARIYA_EMOTION_MODEL_PATH", "data/emotion_predictor.pt"))

# Sidecar metadata written next to the checkpoint (data/emotion_predictor.pt.meta.json):
# trained_at / max_snapshot_id / count / seed_count. train_from_db() writes it so
# the autonomy daemon can decide whether a retrain is due WITHOUT loading the
# model (cheap JSON read, no torch required).
META_SUFFIX = ".meta.json"

# Checkpoint cache: path → loaded model (in eval mode) + file mtime at load,
# so a newly trained checkpoint is picked up without a server restart.
_predictor_cache: Dict[str, Any] = {}
_predictor_mtimes: Dict[str, float] = {}
# Guards the load-then-cache window: the autonomy daemon (event-loop thread)
# and the /api/emotion/predictor endpoint (executor thread) can call
# get_predictor() concurrently — the lock prevents duplicate checkpoint loads.
_predictor_lock = threading.Lock()


# ── Model ─────────────────────────────────────────────────────────────────────

if _TORCH_AVAILABLE:

    class EmotionPredictor(nn.Module):
        """
        LSTM-based predictor modeling the trajectory of a user's emotional state
        to warn the AI of impending frustration / drops in valence.

        Inputs:   (batch, seq_len, INPUT_DIM) — [valence, arousal, trust, ...]
        Outputs:  (pred_continuous [batch, 2], pred_logits [batch, 3])
        """

        def __init__(self, input_dim: int = INPUT_DIM, hidden_dim: int = 64,
                     num_classes: int = NUM_CLASSES):
            super().__init__()
            self.input_dim = input_dim
            self.hidden_dim = hidden_dim
            self.num_classes = num_classes
            self.lstm = nn.LSTM(input_size=input_dim, hidden_size=hidden_dim,
                                batch_first=True)
            self.fc_regression = nn.Linear(hidden_dim, 2)          # Valence & Arousal
            self.fc_classification = nn.Linear(hidden_dim, num_classes)

        def forward(self, x):
            out_lstm, (h_n, _c_n) = self.lstm(x)
            last_hidden = h_n[-1]                                  # (batch, hidden_dim)
            pred_continuous = self.fc_regression(last_hidden)
            pred_logits = self.fc_classification(last_hidden)
            return pred_continuous, pred_logits

else:  # pragma: no cover — torch unavailable stub keeps imports working

    class EmotionPredictor:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise RuntimeError("torch is required for the EmotionPredictor — "
                               "install it with: pip install torch")


# ── Encoding ──────────────────────────────────────────────────────────────────

def _encode_frame(h: dict) -> List[float]:
    """Map a history dict into the fixed 5-D feature vector."""
    return [
        float(h.get("valence", 0.0)),
        float(h.get("arousal", 0.5)),
        float(h.get("trust", 0.5)),
        float(h.get("contradiction", 0.0)),
        min(1.0, float(h.get("word_count", 0)) / 20.0),
    ]


def _encode_history(history: list) -> List[List[float]]:
    """History dicts (chronological) → list of 5-D frames."""
    return [_encode_frame(h) for h in (history or [])]


# ── Training ──────────────────────────────────────────────────────────────────

def build_sequences(records: List[dict], seq_len: int = 8):
    """
    Build supervised windows from chronological records.

    Returns (X, Y) tensors where X[i] = frames[i:i+seq_len] and Y[i] =
    (valence, arousal) of the NEXT frame. Requires >= seq_len + 1 records.
    """
    frames = _encode_history(records)
    X, Y = [], []
    for i in range(len(frames) - seq_len):
        window = frames[i:i + seq_len]
        nxt = frames[i + seq_len]
        X.append(window)
        Y.append([nxt[0], nxt[1]])
    if not X:
        return (torch.tensor([]), torch.tensor([]))
    return (torch.tensor(X, dtype=torch.float32),
            torch.tensor(Y, dtype=torch.float32))


def _pseudo_class(valence: float) -> int:
    """Derive a discrete mood class from future valence for the aux CE loss."""
    if valence < -0.2:
        return 0            # negative / distressed
    if valence > 0.2:
        return 2            # positive
    return 1                # neutral


def train_predictor(records: List[dict], epochs: int = 30, seq_len: int = 8,
                    lr: float = 1e-3, hidden_dim: int = 64,
                    seed: int = 0) -> Optional["EmotionPredictor"]:
    """
    Train the LSTM on chronological emotion records.

    Loss = MSE on the next (valence, arousal) regression + a small auxiliary
    cross-entropy on the derived mood class (makes state_logits meaningful).

    Returns the model in eval mode, or None if not enough data / no torch.
    """
    if not _TORCH_AVAILABLE:
        logger.warning("[EmotionPredictor] torch unavailable — skipping training.")
        return None
    if len(records) < seq_len + 1:
        logger.warning("[EmotionPredictor] Need >= %d records to train, got %d.",
                       seq_len + 1, len(records))
        return None

    torch.manual_seed(seed)
    X, Y = build_sequences(records, seq_len)
    if len(X) == 0:
        return None

    labels = torch.tensor([_pseudo_class(y[0].item()) for y in Y],
                          dtype=torch.long)

    model = EmotionPredictor(input_dim=INPUT_DIM, hidden_dim=hidden_dim,
                             num_classes=NUM_CLASSES)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    mse = torch.nn.MSELoss()
    ce = torch.nn.CrossEntropyLoss()

    model.train()
    for _epoch in range(epochs):
        optimizer.zero_grad()
        pred_cont, pred_cls = model(X)
        loss = mse(pred_cont, Y) + 0.2 * ce(pred_cls, labels)
        loss.backward()
        optimizer.step()
    model.eval()
    logger.info("[EmotionPredictor] Trained %d epochs on %d windows "
                "(final loss %.4f).", epochs, len(X), float(loss.item()))
    return model


def save_model(model: "EmotionPredictor", path: Any) -> None:
    """Persist the model with its hyperparameters."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "state_dict": model.state_dict(),
        "input_dim": model.input_dim,
        "hidden_dim": model.hidden_dim,
        "num_classes": model.num_classes,
    }, path)


def load_model(path: Any) -> "EmotionPredictor":
    """Load a checkpoint saved by save_model()."""
    ckpt = torch.load(Path(path), map_location="cpu", weights_only=True)
    model = EmotionPredictor(input_dim=ckpt["input_dim"],
                             hidden_dim=ckpt["hidden_dim"],
                             num_classes=ckpt["num_classes"])
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model


# ── Inference ─────────────────────────────────────────────────────────────────

def predict_future_state(model: "EmotionPredictor", history: list) -> dict:
    """
    Real LSTM forecast from a history window.

    Returns:
        future_valence / future_arousal / state_logits / state_probs
        distress_risk / escalation_risk / velocity_valence / confidence
    """
    seq = _encode_history(history)
    if not seq:
        return {
            "future_valence": 0.0, "future_arousal": 0.5,
            "state_logits": [0.0] * NUM_CLASSES,
            "state_probs": [1.0 / NUM_CLASSES] * NUM_CLASSES,
            "distress_risk": False, "escalation_risk": False,
            "velocity_valence": 0.0, "confidence": 0.0,
        }

    x = torch.tensor([seq], dtype=torch.float32)
    with torch.no_grad():
        pred_cont, pred_cls = model(x)

    future_valence = float(torch.clamp(pred_cont[0, 0], -1.0, 1.0))
    future_arousal = float(torch.clamp(pred_cont[0, 1], 0.0, 1.0))
    velocity = seq[-1][0] - seq[-2][0] if len(seq) >= 2 else 0.0
    probs = torch.softmax(pred_cls, dim=-1)[0]

    return {
        "future_valence":   round(future_valence, 4),
        "future_arousal":   round(future_arousal, 4),
        "state_logits":     pred_cls[0].tolist(),
        "state_probs":      probs.tolist(),
        "distress_risk":    future_valence < DISTRESS_THRESHOLD,
        "escalation_risk":  velocity < ESCALATION_VELOCITY,
        "velocity_valence": round(velocity, 4),
        "confidence":       min(1.0, len(seq) / 8.0),
    }


def _file_mtime(path: str) -> Optional[float]:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None


def get_predictor(model_path: Any = None, refresh: bool = False):
    """
    Load (and cache) the checkpoint at model_path. Returns None if missing
    or unreadable — callers treat None as "use the heuristic".

    The cache is invalidated when the checkpoint's mtime changes, so a model
    retrained while the server runs is picked up automatically.
    """
    path = str(Path(model_path or MODEL_PATH))
    mtime = _file_mtime(path)
    cached = _predictor_cache.get(path)
    if (cached is not None and not refresh
            and _predictor_mtimes.get(path) == mtime):
        return cached
    if mtime is None:
        return None  # no checkpoint on disk
    with _predictor_lock:
        # Re-check inside the lock so concurrent callers never double-load.
        cached = _predictor_cache.get(path)
        if (cached is not None and not refresh
                and _predictor_mtimes.get(path) == mtime):
            return cached
        try:
            model = load_model(path)
            _predictor_cache[path] = model
            _predictor_mtimes[path] = mtime
            return model
        except Exception as exc:
            logger.debug("[EmotionPredictor] Checkpoint %s unreadable: %s", path, exc)
            return None


def predict_from_history(history: list, model_path: Any = None) -> Optional[dict]:
    """Forecast with the cached checkpoint; None when no model is available."""
    if not _TORCH_AVAILABLE:
        return None
    model = get_predictor(model_path)
    if model is None:
        return None
    return predict_future_state(model, history)


def enrich_prediction(prediction: dict, history: list) -> dict:
    """
    Upgrade a heuristic prediction dict with the trained LSTM when a
    checkpoint exists; otherwise return it unchanged (silent fallback).

    Keeps the keys consumed by ProactiveAIEngine.evaluate():
    distress_risk / escalation_risk / confidence / predicted_valence.

    Corroboration rule: the LSTM may DOWNGRADE risk flags freely (it is the
    more informed signal), but may only UPGRADE them when the recent-window
    heuristic agrees OR its forecast is strongly past the threshold — this
    stops an undertrained model on noisy snapshots from firing spurious
    proactive distress messages.
    """
    if not history or len(history) < 2:
        return prediction
    forecast = predict_from_history(history)
    if forecast is None:
        return prediction

    heuristic_distress = bool(prediction.get("distress_risk", False))
    heuristic_escalation = bool(prediction.get("escalation_risk", False))
    pred_v = forecast["future_valence"]
    velocity = forecast["velocity_valence"]
    conf = forecast["confidence"]

    if conf >= 0.5:
        # Trust the LSTM direction; strong forecasts may override the heuristic.
        distress = bool(forecast["distress_risk"]) and (
            heuristic_distress or pred_v < DISTRESS_THRESHOLD - 0.15)
        escalation = bool(forecast["escalation_risk"]) and (
            heuristic_escalation or velocity < ESCALATION_VELOCITY - 0.1)
    else:
        # Low confidence — keep the heuristic flags.
        distress, escalation = heuristic_distress, heuristic_escalation

    return {
        **prediction,
        "predicted_valence": round(pred_v, 3),
        "distress_risk":     distress,
        "escalation_risk":   escalation,
        "confidence":        max(float(prediction.get("confidence", 0.0)), conf),
        "predictor":         "lstm",
    }


def safe_enrich(prediction: dict, history: list,
                log: Optional[Callable] = None) -> dict:
    """
    enrich_prediction() that never raises — returns the heuristic unchanged on
    any failure (torch absent, corrupt checkpoint, model load error).
    Used by the autonomy daemon / loop as the single wiring point.
    """
    try:
        return enrich_prediction(prediction, history)
    except Exception as exc:
        if log is not None:
            log("LSTM prediction unavailable: %s", exc)
        return prediction


def telemetry(history: list, snapshots: int = 0, sessions: int = 0,
              model_path: Any = None, now: Optional[float] = None) -> dict:
    """
    Compact predictor health/telemetry for dashboards and the autonomy
    daemon's inner-world payload. Field names mirror the status API's meta
    (count / seed_count) so frontend consumers see one consistent schema:

        {
          "status": "trained" | "untrained",   # usable checkpoint loaded?
          "predictor": "lstm" | None,
          "trained_at": epoch | None,
          "checkpoint_age_hours": float | None, # hours since last training
          "count": int,                         # records used at last training
          "seed_count": int,                    # sessions used at last training
          "corpus": {"snapshots": int, "sessions": int},
          "forecast": {...} | None,             # predict_future_state output
        }

    Degrades to "untrained" with a null forecast in the normal failure modes
    (no torch, no checkpoint, too little history). Callers that must never
    raise should still wrap it (the daemon does) — malformed snapshot rows
    (e.g. a NULL valence) could raise inside the torch forward.
    A richer variant (raw meta + history window) lives in
    server/routers/emotion_predictor_router.py.
    """
    meta = read_training_meta(model_path)
    now = time.time() if now is None else now
    trained_at = meta["trained_at"] if meta["trained_at"] > 0 else None

    model = get_predictor(model_path)
    forecast = None
    if model is not None and len(history or []) >= 2:
        forecast = predict_future_state(model, history)

    return {
        "status": "trained" if model is not None else "untrained",
        "predictor": "lstm" if model is not None else None,
        "trained_at": trained_at,
        "checkpoint_age_hours": round((now - trained_at) / 3600, 1) if trained_at else None,
        "count": meta["count"],
        "seed_count": meta["seed_count"],
        "corpus": {"snapshots": snapshots, "sessions": sessions},
        "forecast": forecast,
    }


# ── Self-updating training cadence ────────────────────────────────────────────
# The 24/7 autonomy daemon retrains this model on its own cadence (e.g. every
# 24h) once enough NEW snapshots have accumulated since the last training. The
# decision uses only the sidecar metadata above — no torch — so it is cheap to
# evaluate on every daemon tick.


def _meta_path(model_path: Any = None) -> Path:
    """Sidecar metadata file sitting next to a checkpoint."""
    path = Path(model_path or MODEL_PATH)
    return path.with_suffix(path.suffix + META_SUFFIX)


def read_training_meta(model_path: Any = None) -> dict:
    """
    Read the training metadata sidecar. Never raises — a missing or corrupt
    file yields defaults ("never trained"), so the daemon just waits for
    enough new history.
    """
    try:
        with open(_meta_path(model_path)) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"trained_at": 0.0, "max_snapshot_id": 0, "count": 0, "seed_count": 0}
    return {
        "trained_at": float(data.get("trained_at", 0.0)),
        "max_snapshot_id": int(data.get("max_snapshot_id", 0)),
        "count": int(data.get("count", 0)),
        "seed_count": int(data.get("seed_count", 0)),
    }


def _write_training_meta(model_path: Any, *, trained_at: float,
                         max_snapshot_id: int, count: int,
                         seed_count: int = 0) -> None:
    """Atomically write the training metadata sidecar (tmp + rename)."""
    path = _meta_path(model_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({
        "trained_at": trained_at,
        "max_snapshot_id": max_snapshot_id,
        "count": count,
        "seed_count": seed_count,
    }))
    os.replace(tmp, path)


def should_retrain(max_snapshot_id: int, now: Optional[float] = None, *,
                   min_interval_seconds: float = 24 * 3600,
                   min_new_snapshots: int = 100,
                   seed_records: int = 0,
                   model_path: Any = None) -> Tuple[bool, str]:
    """
    Decide whether a retrain is due.

    A retrain runs when ANY of these holds:
      - the checkpoint is missing (self-heal — don't wait out the interval), or
      - never trained AND enough history exists (`max_snapshot_id` snapshots +
        `seed_records` sessions-table records — so a fresh deployment with real
        session history bootstraps before per-turn snapshots accumulate), or
      - at least `min_new_snapshots` NEW records (snapshots since the last
        training PLUS sessions added since it) AND at least `min_interval_seconds`
        have passed since the last training.

    Returns (due: bool, reason: str) — the reason is for logging/broadcasting.
    """
    now = time.time() if now is None else now
    meta = read_training_meta(model_path)

    if meta["trained_at"] <= 0:
        # Never trained — first checkpoint once enough history has accrued.
        available = max_snapshot_id + seed_records
        if available >= min_new_snapshots:
            return True, "never trained and enough history accrued (snapshots + sessions)"
        return False, f"never trained (only {available} records; need {min_new_snapshots})"

    # Self-heal: the checkpoint itself is gone (deleted / fresh volume) even
    # though the meta survives — rebuild it now instead of waiting out the
    # full interval with no model available.
    if not Path(model_path or MODEL_PATH).exists():
        return True, "checkpoint missing"

    # New records since the last training = new snapshots + new sessions, so a
    # sessions-heavy deployment keeps the model fresh even when per-turn
    # snapshots are sparse.
    new_count = (max_snapshot_id - meta["max_snapshot_id"]) \
        + (seed_records - meta["seed_count"])
    if new_count < min_new_snapshots:
        return False, f"only {new_count} new records (snapshots + sessions) since last training"

    elapsed = now - meta["trained_at"]
    if elapsed < min_interval_seconds:
        return False, f"last training {elapsed / 3600:.1f}h ago (interval not elapsed)"

    return True, "interval elapsed and enough new records accrued"


# ── Training from DB history ──────────────────────────────────────────────────

def _snapshots_from_db(db_path: Any, user_id: Optional[str],
                       limit: int = 20000) -> List[dict]:
    """Read chronological autonomy_snapshots from an explicit SQLite file.

    Deliberately unguarded (unlike _sessions_from_db): snapshots are the
    required corpus, sessions are only an optional bootstrap seed."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if user_id:
            rows = conn.execute(
                "SELECT * FROM autonomy_snapshots WHERE user_id = ? "
                "ORDER BY id ASC LIMIT ?", (user_id, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM autonomy_snapshots ORDER BY id ASC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _session_to_record(row: dict) -> Optional[dict]:
    """
    Map one `sessions`-table row into an emotion record for the LSTM corpus
    (one coarse point per session: avg_valence / avg_arousal). Rows missing
    either value are dropped.
    """
    valence = row.get("avg_valence")
    arousal = row.get("avg_arousal")
    if valence is None or arousal is None:
        return None
    return {
        "valence": float(valence),
        "arousal": float(arousal),
        "trust": 0.5,  # sessions have no trust column — neutral default
    }


def _sessions_to_records(rows: list) -> List[dict]:
    """Raw sessions rows (chronological) → list of emotion records."""
    records = []
    for r in rows:
        rec = _session_to_record(dict(r))
        if rec is not None:
            records.append(rec)
    return records


def _sessions_from_db(db_path: Any, user_id: Optional[str],
                      limit: int = 20000) -> List[dict]:
    """Read the sessions table from an explicit SQLite file as coarse emotion
    records ordered by start_time (oldest first). Never raises — sessions are
    a bootstrap seed, so their absence must not break training."""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            if user_id:
                rows = conn.execute(
                    "SELECT * FROM sessions WHERE user_id = ? "
                    "ORDER BY start_time ASC LIMIT ?", (user_id, limit)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sessions ORDER BY start_time ASC LIMIT ?",
                    (limit,)).fetchall()
            return _sessions_to_records(rows)
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        logger.debug("[EmotionPredictor] sessions table unavailable: %s", exc)
        return []


def train_from_db(epochs: int = 30, seq_len: int = 8, lr: float = 1e-3,
                  hidden_dim: int = 64, user_id: Optional[str] = None,
                  out_path: Any = None, db_path: Any = None,
                  ) -> Optional["EmotionPredictor"]:
    """
    Train the LSTM on real history and save the checkpoint.

    Corpus = coarse per-session emotion records from the `sessions` table
    (avg_valence / avg_arousal — the bootstrap seed), followed chronologically
    by fine-grained `autonomy_snapshots`. This lets training start from real
    session history before per-turn snapshots accumulate.

    Defaults to the live brain DB (server.db.DB_PATH via AutonomyStore); pass
    db_path for an explicit SQLite file. Returns the trained model or None
    when there is not enough combined history.
    """
    if db_path is not None:
        snapshots = _snapshots_from_db(db_path, user_id)
        sessions = _sessions_from_db(db_path, user_id)
    else:
        from server.autonomy.state import AutonomyStore
        store = AutonomyStore()
        snapshots = store.get_snapshot_history(user_id=user_id)
        sessions = _sessions_to_records(store.get_session_history(user_id=user_id))

    records = sessions + snapshots  # chronological: sessions then snapshots
    if len(records) < seq_len + 1:
        logger.warning("[EmotionPredictor] Not enough history to train "
                       "(%d < %d+1).", len(records), seq_len)
        return None

    model = train_predictor(records, epochs=epochs, seq_len=seq_len,
                            lr=lr, hidden_dim=hidden_dim)
    if model is None:
        return None
    out = Path(out_path or MODEL_PATH)
    save_model(model, out)
    # Record where training stopped so the autonomy daemon can decide when a
    # retrain is due (new-snapshot watermark + interval) without loading torch.
    max_id = max((int(r.get("id") or 0) for r in snapshots), default=0)
    _write_training_meta(out, trained_at=time.time(),
                         max_snapshot_id=max_id, count=len(records),
                         seed_count=len(sessions))
    logger.info("[EmotionPredictor] Checkpoint saved to %s (%d records: "
                "%d sessions + %d snapshots).",
                out, len(records), len(sessions), len(snapshots))
    return model


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m server.systems.emotion.predictor",
        description="Train the LSTM emotion predictor on autonomy snapshot history.")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--seq-len", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--hidden-dim", type=int, default=64)
    parser.add_argument("--user", default=None, help="train on one user only")
    parser.add_argument("--db", default=None, help="explicit SQLite file")
    parser.add_argument("--out", default=str(MODEL_PATH))
    args = parser.parse_args(argv)

    model = train_from_db(epochs=args.epochs, seq_len=args.seq_len, lr=args.lr,
                          hidden_dim=args.hidden_dim, user_id=args.user,
                          out_path=args.out, db_path=args.db)
    if model is None:
        print("Training skipped — not enough snapshot history (need > seq_len).",
              file=sys.stderr)
        return 1
    print(f"Trained LSTM emotion predictor -> {args.out}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
