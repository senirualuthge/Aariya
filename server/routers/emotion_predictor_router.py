"""
emotion_predictor_router.py
───────────────────────────
FastAPI router exposing the LSTM emotion predictor's training status and
latest forecast to the dashboard.

Endpoints:
  GET /api/emotion/predictor?user_id=user_default&window=40
      {
        "status":         "trained" | "untrained",   # usable checkpoint exists?
        "predictor":      "lstm" | null,
        "meta":           {trained_at, max_snapshot_id, count, seed_count},
        "corpus":         {snapshots, sessions},      # rows currently in the DB
        "forecast":       {...} | null,               # latest LSTM forecast
        "history_window": [{valence, arousal, trust} ...],  # frames used
        "window_used":    int
      }

Never raises: without torch, a checkpoint, or enough history it reports
"untrained" / null forecast so the UI degrades gracefully.

Mount in main.py:
  from server.routers.emotion_predictor_router import router as emotion_predictor_router
  app.include_router(emotion_predictor_router)
"""

import asyncio
import logging

from fastapi import APIRouter

logger = logging.getLogger("aariya.emotion_predictor_api")
router = APIRouter(prefix="/api/emotion", tags=["Emotion Predictor"])

MIN_WINDOW = 2
MAX_WINDOW = 200


def _status_payload(user_id: str, window: int) -> dict:
    """Build the predictor status + forecast payload (pure sync work — SQLite
    reads, a cached checkpoint load, and one small torch forward)."""
    from server.autonomy.state import AutonomyStore
    from server.systems.emotion import predictor

    store = AutonomyStore()
    meta = predictor.read_training_meta(predictor.MODEL_PATH)

    history = store.get_snapshot_history(user_id=user_id, limit=window)
    history = history[-window:]

    frames = [
        {
            "valence": float(h.get("valence", 0.0)),
            "arousal": float(h.get("arousal", 0.5)),
            "trust": float(h.get("trust", 0.5)),
        }
        for h in history
    ]

    model = predictor.get_predictor()
    forecast = None
    if model is not None and len(history) >= MIN_WINDOW:
        forecast = predictor.predict_future_state(model, history)

    # Corpus readout is GLOBAL (all users) to match train_from_db(), which
    # trains on every user's history — meta.count and corpus must agree.
    return {
        "status": "trained" if model is not None else "untrained",
        "predictor": "lstm" if model is not None else None,
        "method": "lstm" if model is not None else "heuristic",
        "meta": meta,
        "corpus": {
            "snapshots": store.get_snapshot_count(),
            "sessions": store.get_session_count(),
        },
        "forecast": forecast,
        "history_window": frames,
        "window_used": len(history),
    }


@router.get("/predictor")
async def predictor_status(user_id: str = "user_default", window: int = 40):
    """Training status + latest forecast for the emotion predictor."""
    window = max(MIN_WINDOW, min(window, MAX_WINDOW))
    try:
        # DB reads + checkpoint load + torch forward — run off the event loop
        # so this endpoint never janks the cognitive pipeline.
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: _status_payload(user_id, window)
        )
    except Exception as exc:
        logger.warning("[emotion/predictor] status unavailable: %s", exc)
        return {
            "status": "untrained",
            "predictor": None,
            "method": "heuristic",
            "meta": {"trained_at": 0.0, "max_snapshot_id": 0,
                     "count": 0, "seed_count": 0},
            "corpus": {"snapshots": 0, "sessions": 0},
            "forecast": None,
            "history_window": [],
            "window_used": 0,
            "error": str(exc),
        }
