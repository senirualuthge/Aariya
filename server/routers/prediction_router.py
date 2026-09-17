"""
prediction_router.py
────────────────────
FastAPI router exposing the unified PredictionEngine to the dashboard/mobile.

Endpoints:
  GET  /api/prediction/status          → engine snapshot (predictions, accuracy,
                                         beliefs, recent events)
  POST /api/prediction/predict         → run a prediction from feature input
  POST /api/prediction/verify          → verify a stored prediction by id

Graceful when the engine's optional heavy deps (chromadb/torch) are absent —
the core is model-free and always runs.
"""

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger("aariya.prediction_api")
router = APIRouter(prefix="/api/prediction", tags=["Prediction Engine"])

from server.systems.prediction.prediction_core import (
    PredictionEngine,
    PredictionRequest,
    get_prediction_engine,
)

# Shared, persisted engine — same store the brain_v2 / daemon read/write.
_engine = get_prediction_engine()


class PredictRequest(BaseModel):
    features: dict
    domain: str = "general"
    entity: str = "user"


class VerifyRequest(BaseModel):
    prediction_id: str
    outcome: str
    correct: bool


@router.get("/status")
def status():
    return _engine.snapshot()


@router.get("/world-state")
def world_state():
    """The persisted World State Snapshot — single source of truth for the
    brain, daemon, and prediction layers (NEWPredictionPRT2 §"4. Single
    Source of Truth"). No subsystem holds a separate authoritative copy."""
    from server.systems.world_model.world_state import get_world_state
    return get_world_state().snapshot()


@router.post("/predict")
def predict(req: PredictRequest):
    out = _engine.core.predict(
        PredictionRequest(
            domain=req.domain, entity=req.entity,
            horizon="short", features=req.features,
        )
    )
    _engine.store.add(
        f"{req.domain} outcome ~{out.value:.2f}", out.confidence,
        domain=req.domain, entity=req.entity,
    )
    return {
        "value": out.value,
        "confidence": out.confidence,
        "uncertainty": out.uncertainty,
        "reasoning_trace": out.reasoning_trace,
    }


@router.post("/verify")
def verify(req: VerifyRequest):
    entry = _engine.store.verify(req.prediction_id, req.outcome, correct=req.correct)
    if entry is None:
        return {"status": "not_found"}
    return {"status": "ok", "entry": entry, "accuracy": _engine.store.accuracy()}


@router.get("/calibration")
def calibration():
    """Per-domain accuracy + overconfidence misses (NEWPredictionPRT2 §3/§15).
    Runs a verification pass against the recorded outcome when one exists so
    the numbers reflect the closed loop, not just stored predictions."""
    from server.systems.prediction.verifier import PredictionVerifier
    verifier = PredictionVerifier(_engine)
    verifier.verify_due(resolver=None)
    return verifier.metrics()


@router.get("/causal-graph")
def causal_graph():
    """Causal chains + learned edges + counterfactual explanations."""
    return {
        "edges": [
            {"source": e.source, "relation": e.relation, "target": e.target,
             "confidence": e.confidence}
            for e in _engine.causal_graph.edges
        ],
        "chains": {
            start: _engine.causal_graph.propagate(start)
            for start in {e.source for e in _engine.causal_graph.edges}
        },
    }


@router.get("/strategic")
def strategic_memory():
    """Reusable plans, known failures with instant recovery, and promoted
    principles (NEWPredictionPRT2 §10/§6/§Lessons)."""
    from server.systems.prediction.strategic_memory import StrategicMemory
    sm = StrategicMemory()
    snap = sm.snapshot()
    return {
        "plans": snap["plans"],
        "failures": [
            {"failure": f, "solution": s}
            for f, s in sm.failures.failures.items()
        ],
        "principles": snap["lessons"].get("principles", []),
    }


@router.get("/forecast")
def forecast(value: float = 0.5, drift: float = 0.0):
    """Multi-horizon forecast ladder (1h/1d/1w/1m) for a scalar state value,
    plus the learned-forecast model state (trained / samples / loss)."""
    horizons = _engine.core.forecast_horizons({"value": value, "drift": drift})
    horizon_value = horizons["horizons"]["1d"]["value"]
    series = _engine.core.predict_future(
        {"value": value, "confidence": horizons["horizons"]["1d"]["confidence"]}, steps=3)
    return {
        **horizons,
        "learned_series": series,
        "forecast_model": _engine.core.forecast_model.state(),
    }


@router.post("/forecast/learn")
def learn_forecast():
    """Train the learned forecast head on the store's verified prediction→actual
    transitions (NEWPredictionPRT2 §ForecastModel)."""
    return _engine.learn_forecast()


@router.get("/beliefs")
def beliefs():
    """Named belief store (NEWPredictionPRT2 §Phase 19): strongest beliefs,
    promoted working assumptions, and per-belief evidence counts."""
    return {
        "top": _engine.beliefs.top(10),
        "promoted": _engine.beliefs.promoted(),
        "total": len(_engine.beliefs.beliefs),
    }


@router.post("/beliefs/promote")
def promote_belief(belief_key: str):
    """Manually run the promotion check for one belief (evidence-gated)."""
    return {"belief": belief_key, "promoted": _engine.beliefs.promote(belief_key)}


@router.post("/beliefs/consolidate")
def consolidate_beliefs():
    """Merge near-duplicate beliefs, decay stale ones, prune weak ones."""
    return _engine.beliefs.consolidate()
