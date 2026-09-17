"""
Prediction core — the unified, domain-agnostic prediction engine.

Implements the non-financial core of the PREDICTION_ENGINE_UNIFIED doc:

  * PredictionStore   — every prediction is tracked and verifiable.
  * PredictionCore    — feature fusion → value + confidence + uncertainty.
  * WorldMemory       — timestamped event timeline with recency windows.
  * BeliefEngine      — evolving beliefs with evidence-weighted updates.
  * DecisionMemory    — decision + outcome history for smarter future routing.
  * CausalGraph       — causal edges with confidence/lag; propagation chains.

The financial/trading feature set in the source docs is explicitly
DEPRECATED and OUT OF SCOPE (see the doc's DEPRECATION NOTICE) — nothing here
touches markets or prices.
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.prediction")


# ── Prediction Registry ────────────────────────────────────────────────────────

class PredictionStore:
    def __init__(self, max_entries: int = 1000, persist_path: Optional[str] = None):
        self.predictions: List[Dict[str, Any]] = []
        self._max = max_entries
        self._persist_path = persist_path
        if persist_path:
            self._load()

    def add(self, prediction: str, confidence: float, expected_date: Optional[str] = None,
            *, domain: str = "general", entity: str = "user", value: Optional[float] = None) -> Dict[str, Any]:
        entry = {
            "id": hashlib.md5(f"{time.time()}:{prediction}".encode()).hexdigest()[:10],
            "prediction": prediction,
            "confidence": round(float(confidence), 3),
            "expected_date": expected_date,
            "domain": domain,
            "entity": entity,
            "added_at": time.time(),
            "verified": False,
            "actual_outcome": None,
            "predicted_value": round(float(value), 4) if value is not None else None,
            "actual_value": None,
            "error": None,
        }
        self.predictions.append(entry)
        if len(self.predictions) > self._max:
            self.predictions.pop(0)
        self._save()
        return entry

    def verify(self, prediction_id: str, outcome: str, *, correct: bool,
               actual_value: Optional[float] = None) -> Optional[Dict[str, Any]]:
        for entry in self.predictions:
            if entry["id"] == prediction_id:
                entry["verified"] = True
                entry["actual_outcome"] = outcome
                entry["correct"] = bool(correct)
                if actual_value is not None:
                    entry["actual_value"] = round(float(actual_value), 4)
                    pred = entry.get("predicted_value")
                    if pred is not None:
                        entry["error"] = round(abs(float(pred) - float(actual_value)), 4)
                self._save()
                return entry
        return None

    def _save(self) -> None:
        if not self._persist_path:
            return
        try:
            import os
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump({"predictions": self.predictions}, f, indent=2)
        except OSError as exc:
            logger.warning("[PredictionStore] persist failed: %s", exc)

    def _load(self) -> None:
        if not self._persist_path:
            return
        try:
            import os
            if not os.path.exists(self._persist_path):
                return
            with open(self._persist_path, encoding="utf-8") as f:
                data = json.load(f)
            self.predictions = data.get("predictions", [])
            logger.info("[PredictionStore] loaded %d persisted predictions", len(self.predictions))
        except Exception as exc:
            logger.warning("[PredictionStore] load failed (fresh start): %s", exc)

    def unverified(self) -> List[Dict[str, Any]]:
        return [p for p in self.predictions if not p["verified"]]

    def accuracy(self) -> float:
        verified = [p for p in self.predictions if p.get("verified")]
        if not verified:
            return 0.0
        return sum(1 for p in verified if p.get("correct")) / len(verified)


# ── Core prediction (domain-agnostic) ──────────────────────────────────────────

@dataclass
class PredictionRequest:
    domain: str
    entity: str
    horizon: str = "short"
    features: Dict[str, float] = field(default_factory=dict)


@dataclass
class PredictionOutput:
    value: float
    confidence: float
    uncertainty: float
    reasoning_trace: List[str]
    model_version: str = "core-v1"


class PredictionCore:
    """
    Feature-fusion predictor. Deterministic signal mixing + confidence from
    agreement across features. Kept model-free (no torch required) so it
    always runs; a learned head can replace `_score` later.
    """

    MODEL_VERSION = "core-v2"

    def __init__(self) -> None:
        # Bias-correction for confidence calibration (NEWPredictionPRT2
        # §Phase 15 / core recalibration): a negative offset means the model
        # is overconfident and confidence gets damped until it self-corrects.
        self._confidence_bias: float = 0.0
        self._calibration_count: int = 0
        self._calibration_version: str = self.MODEL_VERSION
        # Learned forecast head (NEWPredictionPRT2 §ForecastModel): trained on
        # verified (predicted → actual) transitions; falls back to a bounded
        # walk when untrained or torch-less.
        from server.systems.prediction.forecast_model import ForecastModel
        self.forecast_model = ForecastModel()

    def predict(self, req: PredictionRequest) -> PredictionOutput:
        features = req.features or {}
        if not features:
            return PredictionOutput(
                value=0.0, confidence=0.1, uncertainty=0.9,
                reasoning_trace=["no features"], model_version=self.MODEL_VERSION,
            )
        vals = list(features.values())
        mean = sum(vals) / len(vals)
        # Agreement → confidence: low spread of normalized features.
        spread = (max(vals) - min(vals)) / max(1e-6, (abs(mean) + 1))
        confidence = max(0.1, min(0.99, 1.0 - spread))
        # Apply bias-correction learned from verification feedback.
        calibrated = max(0.05, min(0.99, confidence + self._confidence_bias))
        value = max(0.0, min(1.0, (mean + 1) / 2))
        return PredictionOutput(
            value=round(value, 3),
            confidence=round(calibrated, 3),
            uncertainty=round(1 - calibrated, 3),
            reasoning_trace=[
                f"Analyzed {req.domain} signals",
                f"Entity: {req.entity}",
                f"Horizon: {req.horizon}",
                f"features={len(features)}, mean={mean:.2f}, spread={spread:.2f}",
                f"calibrated: bias={self._confidence_bias:.3f}",
            ],
            model_version=self.MODEL_VERSION,
        )

    def calibrate(self, verification_samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Recalibrate confidence from verification feedback (drift→retrain).

        Each sample: {"confidence": predicted, "correct": 0|1, "value": pv}.
        If the model is overconfident (mean predicted confidence > actual hit
        rate) it learns a negative bias; underconfident learns a positive one.
        Only shifts when enough samples accumulate, mirroring a soft retrain.
        """
        if not verification_samples:
            return {"calibrated": False, "reason": "no samples"}
        predicted = [max(0.05, min(0.99, float(s["confidence"]))) for s in verification_samples]
        correct = [1 if s.get("correct") else 0 for s in verification_samples]
        mean_pred = sum(predicted) / len(predicted)
        hit_rate = sum(correct) / len(correct)
        bias = (hit_rate - mean_pred) * 0.5  # damped correction step
        self._confidence_bias = max(-0.3, min(0.3, self._confidence_bias + bias))
        self._calibration_count = len(verification_samples)
        self._calibration_version = f"core-v2-cal-{self._calibration_count}"
        return {
            "calibrated": True,
            "mean_predicted": round(mean_pred, 3),
            "hit_rate": round(hit_rate, 3),
            "bias": round(self._confidence_bias, 3),
            "samples": len(verification_samples),
            "version": self._calibration_version,
        }

    def drift_recalibrate(self, drift: Dict[str, Any]) -> Dict[str, Any]:
        """Retrain hook when concept drift is detected: widen confidence
        (raise uncertainty) proportionally to the measured shift so the model
        acknowledges it is operating outside its trained regime."""
        if not drift.get("drift_detected"):
            return {"recalibrated": False}
        shift = max(0.0, min(0.3, float(drift.get("shift_score", 0.0)) * 0.15))
        self._confidence_bias -= shift
        return {
            "recalibrated": True,
            "shift": round(shift, 3),
            "bias": round(self._confidence_bias, 3),
        }

    def calibration_state(self) -> Dict[str, Any]:
        return {
            "bias": round(self._confidence_bias, 3),
            "samples": self._calibration_count,
            "version": self._calibration_version,
        }

    def predict_future(self, state: Dict[str, float], steps: int = 5) -> List[float]:
        """Continuation of a scalar feature.

        Uses the learned ForecastModel when trained (NEWPredictionPRT2
        §ForecastModel — "no automatic improvement loop"); otherwise falls back
        to a bounded momentum/random-walk simulation. Pass confidence in the
        state dict to inform the learned head.
        """
        return self.forecast_model.predict(state, steps=steps)

    def forecast_horizons(self, state: Dict[str, float]) -> Dict[str, Any]:
        """Multi-horizon forecast (NEWPredictionPRT2 §Phase 19).

        Predicts the same scalar feature at 1h / 1d / 1w / 1m horizons. Each
        horizon widens its uncertainty band (further out = less certain) and
        uses a decayed confidence so the brain can plan at different timescales
        (short-horizon de-escalation vs long-horizon goal support).
        """
        import random
        current = float(state.get("value", 0.5))
        drift = float(state.get("drift", 0.0))  # persistent bias, if known
        horizons = [("1h", 0.5), ("1d", 1.5), ("1w", 4.0), ("1m", 12.0)]
        out: Dict[str, Any] = {"horizons": {}}
        value = current
        for label, scale in horizons:
            value += drift + random.uniform(-0.05 * scale, 0.05 * scale)
            value = max(0.0, min(1.0, value))
            uncertainty = min(0.95, 0.25 + scale * 0.06)
            out["horizons"][label] = {
                "value": round(value, 3),
                "confidence": round(max(0.05, 1.0 - uncertainty), 3),
                "uncertainty": round(uncertainty, 3),
                "band": round(0.08 * scale, 3),
            }
        out["direction"] = (
            "rising" if out["horizons"]["1m"]["value"] > current + 0.05
            else "falling" if out["horizons"]["1m"]["value"] < current - 0.05
            else "stable"
        )
        return out


# ── World Memory (event timeline) ─────────────────────────────────────────────

class WorldMemory:
    def __init__(self, max_events: int = 2000, persist_path: Optional[str] = None):
        self.events: List[Dict[str, Any]] = []
        self._max = max_events
        self._persist_path = persist_path
        if persist_path:
            self._load()

    def store(self, event: Dict[str, Any]) -> None:
        self.events.append({"timestamp": time.time(), **event})
        if len(self.events) > self._max:
            self.events.pop(0)
        self._save()

    def recent(self, days: float = 30) -> List[Dict[str, Any]]:
        cutoff = time.time() - (days * 86400)
        return [e for e in self.events if e.get("timestamp", 0) > cutoff]

    def events_for(self, entity: str, days: float = 30) -> List[Dict[str, Any]]:
        return [e for e in self.recent(days) if e.get("entity") == entity]

    def _save(self) -> None:
        if not self._persist_path:
            return
        try:
            import os
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump({"events": self.events}, f, indent=2)
        except OSError as exc:
            logger.warning("[WorldMemory] persist failed: %s", exc)

    def _load(self) -> None:
        if not self._persist_path:
            return
        try:
            import os
            if not os.path.exists(self._persist_path):
                return
            with open(self._persist_path, encoding="utf-8") as f:
                data = json.load(f)
            self.events = data.get("events", [])
            logger.info("[WorldMemory] loaded %d persisted events", len(self.events))
        except Exception as exc:
            logger.warning("[WorldMemory] load failed (fresh start): %s", exc)


# ── Belief Engine ─────────────────────────────────────────────────────────────

class BeliefEngine:
    """
    Beliefs are confidence-weighted statements, updated by new evidence:
        belief = belief * (1 - lr) + evidence * lr

    Each belief additionally tracks an evidence count, can be PROMOTED to a
    working assumption when it has accumulated enough confirming evidence, and
    can be consolidated (near-duplicate beliefs merge, weak stale ones decay
    away) — the named belief-store layer the AGI Claims / prediction specs
    call for (NEWPredictionPRT2 §Phase 19 belief model).
    """

    PROMOTE_MIN_EVIDENCE = 3      # evidence events needed before promotion
    PROMOTE_CONFIDENCE = 0.62     # and a confidence above this floor
    CONSOLIDATE_MAX_AGE_DAYS = 90 # beliefs not touched for this long decay

    def __init__(self, learning_rate: float = 0.2, persist_path: Optional[str] = None):
        self.beliefs: Dict[str, Dict[str, Any]] = {}
        self.lr = learning_rate
        self._persist_path = persist_path
        if persist_path:
            self._load()

    def _entry(self, belief: str) -> Dict[str, Any]:
        return self.beliefs.setdefault(belief, {
            "confidence": 0.5,
            "evidence_count": 0,
            "promoted": False,
            "sources": [],
            "last_verified": time.time(),
        })

    def set(self, belief: str, confidence: float, *, sources: Optional[List[str]] = None) -> None:
        entry = self._entry(belief)
        entry["confidence"] = round(float(confidence), 3)
        if sources:
            entry["sources"] = list(entry.get("sources", [])) + list(sources)
        entry["last_verified"] = time.time()
        self._save()

    def update(self, belief: str, evidence: float) -> float:
        # First piece of evidence anchors the belief at the observed value
        # (matches the original first-update semantics); later evidence moves
        # it by the learning rate and accrues an evidence count.
        if belief not in self.beliefs:
            entry = self._entry(belief)
            entry["confidence"] = round(float(evidence), 3)
            entry["evidence_count"] = 1
            entry["last_verified"] = time.time()
            self._save()
            return float(entry["confidence"])
        entry = self._entry(belief)
        current = entry.get("confidence", 0.5)
        new = current * (1 - self.lr) + float(evidence) * self.lr
        entry["confidence"] = round(new, 3)
        entry["evidence_count"] = int(entry.get("evidence_count", 0)) + 1
        entry["last_verified"] = time.time()
        self._save()
        return new

    def confirm(self, belief: str, strength: float = 0.6) -> float:
        """Positive evidence: strengthen toward 1.0 and count it."""
        return self.update(belief, max(0.5, float(strength)))

    def disconfirm(self, belief: str, strength: float = 0.3) -> float:
        """Negative evidence: pull toward 0 and count it (weakens promotion)."""
        return self.update(belief, min(0.4, float(strength)))

    def promote(self, belief: str) -> bool:
        """Promote a well-evidenced belief to a working assumption.

        A belief is promoted when it has accumulated enough evidence events
        AND its confidence clears the promotion floor. Promotion is sticky
        until later evidence drops the confidence back below the floor.
        """
        entry = self._entry(belief)
        count = int(entry.get("evidence_count", 0))
        conf = float(entry.get("confidence", 0.5))
        if count >= self.PROMOTE_MIN_EVIDENCE and conf >= self.PROMOTE_CONFIDENCE:
            entry["promoted"] = True
        elif conf < self.PROMOTE_CONFIDENCE - 0.15:
            entry["promoted"] = False
        self._save()
        return bool(entry.get("promoted"))

    def consolidate(self, *, merge_threshold: float = 0.06) -> Dict[str, Any]:
        """Housekeeping: merge near-duplicate belief keys (same content words),
        decay stale beliefs, and prune weak/empty ones. Returns what changed.

        Near-duplicate detection is a cheap token-overlap proxy on the belief
        statement — two beliefs whose key tokens overlap ≥ 70% merge into the
        one with more evidence.
        """
        merged = 0
        dropped = 0
        keys = list(self.beliefs.keys())
        now = time.time()

        def _tokens(k: str):
            return set(k.lower().replace("_", " ").split())

        for i, a in enumerate(keys):
            if a not in self.beliefs:
                continue
            ta = _tokens(a)
            if not ta:
                continue
            for b in keys[i + 1:]:
                if b not in self.beliefs:
                    continue
                tb = _tokens(b)
                if not tb:
                    continue
                overlap = len(ta & tb) / min(len(ta), len(tb))
                if overlap >= 0.7 and (len(ta) == len(tb) or len(ta & tb) >= 2):
                    keeper, loser = (a, b) if (
                        self.beliefs[a].get("evidence_count", 0)
                        >= self.beliefs[b].get("evidence_count", 0)
                    ) else (b, a)
                    keeper_entry = self._entry(keeper)
                    keeper_entry["confidence"] = round(max(
                        float(keeper_entry.get("confidence", 0.5)),
                        float(self.beliefs[loser].get("confidence", 0.5)),
                    ), 3)
                    keeper_entry["evidence_count"] = int(keeper_entry.get("evidence_count", 0)) \
                        + int(self.beliefs[loser].get("evidence_count", 0))
                    keeper_entry["promoted"] = bool(keeper_entry.get("promoted")
                                                     or self.beliefs[loser].get("promoted"))
                    del self.beliefs[loser]
                    merged += 1

        # Age-out: beliefs untouched for too long lose confidence; below a
        # floor they are dropped (they stopped being live beliefs).
        for key in list(self.beliefs.keys()):
            entry = self.beliefs[key]
            age_days = (now - float(entry.get("last_verified", now))) / 86400.0
            if age_days > self.CONSOLIDATE_MAX_AGE_DAYS:
                entry["confidence"] = round(max(0.0, float(entry["confidence"]) - 0.1), 3)
            if float(entry.get("confidence", 0.0)) < 0.12 and not entry.get("promoted"):
                del self.beliefs[key]
                dropped += 1
        self._save()
        return {"merged": merged, "dropped": dropped, "remaining": len(self.beliefs)}

    def promoted(self) -> List[Dict[str, Any]]:
        """Working assumptions: promoted beliefs, strongest first."""
        out = [
            {"belief": k, "confidence": v["confidence"],
             "evidence_count": v.get("evidence_count", 0)}
            for k, v in self.beliefs.items() if v.get("promoted")
        ]
        out.sort(key=lambda x: x["confidence"], reverse=True)
        return out

    def top(self, n: int = 5) -> List[Dict[str, Any]]:
        """Strongest beliefs regardless of promotion status."""
        out = [
            {"belief": k, "confidence": v["confidence"],
             "evidence_count": v.get("evidence_count", 0),
             "promoted": bool(v.get("promoted"))}
            for k, v in self.beliefs.items()
        ]
        out.sort(key=lambda x: x["confidence"], reverse=True)
        return out[:n]

    def get(self, belief: str) -> Optional[float]:
        entry = self.beliefs.get(belief)
        return entry["confidence"] if entry else None

    def _save(self) -> None:
        if not self._persist_path:
            return
        try:
            import os
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump({"beliefs": self.beliefs}, f, indent=2)
        except OSError as exc:
            logger.warning("[BeliefEngine] persist failed: %s", exc)

    def _load(self) -> None:
        if not self._persist_path:
            return
        try:
            import os
            if not os.path.exists(self._persist_path):
                return
            with open(self._persist_path, encoding="utf-8") as f:
                data = json.load(f)
            self.beliefs = data.get("beliefs", {})
            logger.info("[BeliefEngine] loaded %d persisted beliefs", len(self.beliefs))
        except Exception as exc:
            logger.warning("[BeliefEngine] load failed (fresh start): %s", exc)


# ── Decision Memory ───────────────────────────────────────────────────────────

class DecisionMemory:
    def __init__(self, max_entries: int = 500, persist_path: Optional[str] = None):
        self.decisions: List[Dict[str, Any]] = []
        self._max = max_entries
        self._persist_path = persist_path
        if persist_path:
            self._load()

    def save(self, context: Dict[str, Any], decision: str, outcome: str, reward: float) -> None:
        self.decisions.append({
            "context": context,
            "decision": decision,
            "outcome": outcome,
            "reward": float(reward),
            "timestamp": time.time(),
        })
        if len(self.decisions) > self._max:
            self.decisions.pop(0)
        self._save()

    def retrieve_similar(self, context: Dict[str, Any], top_k: int = 5) -> List[Dict[str, Any]]:
        scored = []
        for d in self.decisions:
            common = set(context.keys()) & set(d["context"].keys())
            if not common:
                continue
            matches = sum(
                1 for k in common if str(context[k]).lower() == str(d["context"][k]).lower()
            )
            overlap = matches / max(len(context), 1)
            if overlap > 0.3:
                scored.append((d, overlap))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [entry for entry, _ in scored[:top_k]]

    def _save(self) -> None:
        if not self._persist_path:
            return
        try:
            import os
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump({"decisions": self.decisions}, f, indent=2)
        except OSError as exc:
            logger.warning("[DecisionMemory] persist failed: %s", exc)

    def _load(self) -> None:
        if not self._persist_path:
            return
        try:
            import os
            if not os.path.exists(self._persist_path):
                return
            with open(self._persist_path, encoding="utf-8") as f:
                data = json.load(f)
            self.decisions = data.get("decisions", [])
            logger.info("[DecisionMemory] loaded %d persisted decisions", len(self.decisions))
        except Exception as exc:
            logger.warning("[DecisionMemory] load failed (fresh start): %s", exc)


# ── Causal Graph ──────────────────────────────────────────────────────────────

@dataclass
class CausalEdge:
    source: str
    relation: str
    target: str
    confidence: float = 0.9
    lag_days: int = 0
    source_refs: List[str] = field(default_factory=list)


class CausalGraph:
    def __init__(self):
        self.edges: List[CausalEdge] = []

    def add_edge(self, edge: CausalEdge) -> None:
        self.edges.append(edge)

    def successors(self, node: str) -> List[CausalEdge]:
        return [e for e in self.edges if e.source == node]

    def predecessors(self, node: str) -> List[CausalEdge]:
        return [e for e in self.edges if e.target == node]

    def propagate(self, start_node: str, confidence: float = 1.0,
                  elapsed_days: int = 0, path: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        path = path or [start_node]
        results = []
        for edge in self.successors(start_node):
            new_confidence = confidence * edge.confidence
            total_days = elapsed_days + edge.lag_days
            new_path = path + [edge.target]
            results.append({
                "path": new_path,
                "confidence": round(new_confidence, 3),
                "days": total_days,
                "relation": edge.relation,
            })
            results.extend(self.propagate(edge.target, new_confidence, total_days, new_path))
        return results


# ── Multi-Scenario Planning ───────────────────────────────────────────────────

_SCENARIO_NAMES = ("best", "expected", "worst")


class ScenarioPlanner:
    """Multi-Scenario Planning (NEWPredictionPRT2 §"6. Multi-Scenario Planning").

    Instead of returning one linear plan, produces three branches — Best /
    Expected / Worst — each projecting the same scalar state forward under
    different assumption bands. This is the doc's "predict(state, candidate)
    → Future A/B/C": the brain plans at each scenario and knows which real
    signal would land it in which branch.
    """

    def plan(self, value: float = 0.5, confidence: float = 0.5,
             steps: int = 3, spread: float = 0.08) -> Dict[str, Any]:
        """Generate Best/Expected/Worst scenario trajectories for a state value.

        Expected keeps the current value (mean-reverting drift); Best assumes a
        favorable drift; Worst assumes an adverse drift proportional to the
        model's uncertainty (1 - confidence). Each scenario carries a
        probability weight (confidence-weighted) and a trigger describing the
        observable signal that would realize it.
        """
        value = max(0.0, min(1.0, float(value)))
        confidence = max(0.05, min(0.95, float(confidence)))
        uncertainty = 1.0 - confidence
        spread = max(0.01, min(0.3, float(spread)))

        def _trajectory(base: float, per_step: float, sign: float) -> List[float]:
            out = []
            cur = base
            for i in range(1, steps + 1):
                # Each step decays toward the per-branch drift so long horizons
                # stay bounded; Worst drifts at uncertainty * spread.
                cur = max(0.0, min(1.0, cur + sign * per_step * (1 - i / (steps + 1))))
                out.append(round(cur, 3))
            return out

        expected_step = spread * 0.25          # mild mean-reversion
        best_step = spread                      # favorable assumption
        worst_step = spread * (0.5 + uncertainty)  # adverse, uncertainty-scaled

        scenarios: Dict[str, Any] = {
            "best": {
                "value": round(min(1.0, value + spread), 3),
                "trajectory": _trajectory(value, best_step, 1.0),
                "probability": round(0.5 * confidence + 0.25, 3),
                "trigger": "continued positive signal (valence/trust rising)",
            },
            "expected": {
                "value": round(value, 3),
                "trajectory": _trajectory(value, expected_step, 0.0),
                "probability": round(0.5 * confidence + 0.5, 3),
                "trigger": "no new significant signal",
            },
            "worst": {
                "value": round(max(0.0, value - spread * (0.5 + uncertainty)), 3),
                "trajectory": _trajectory(value, worst_step, -1.0),
                "probability": round(0.5 * uncertainty + 0.25, 3),
                "trigger": "adverse signal / contradiction (confidence low → risk high)",
            },
        }
        return {
            "value": round(value, 3),
            "confidence": round(confidence, 3),
            "steps": steps,
            "dominant": max(_SCENARIO_NAMES, key=lambda s: scenarios[s]["probability"]),
            "scenarios": scenarios,
        }

    def plan_for_action(self, candidate: Dict[str, Any],
                        state: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """Scenario-plan a single candidate action using its predicted outcome."""
        state = state or {}
        base = float(candidate.get("predicted_value",
                                   float(state.get("valence", 0.0))))
        conf = float(candidate.get("confidence",
                                   float(state.get("trust", 0.5))))
        return self.plan(value=base, confidence=conf)


# ── Facade ────────────────────────────────────────────────────────────────────

class PredictionEngine:
    """Convenience facade tying the prediction components together.

    All sub-stores persist to a shared directory when `persist_dir` is given
    so predictions, world events, beliefs, and decisions survive restarts
    (NEWPredictionPRT2 §Phase 2.5 / §Phase 4 persistent world model).
    """

    def __init__(self, persist_dir: str = "./data/prediction"):
        self.persist_dir = persist_dir
        self.store = PredictionStore(persist_path=f"{persist_dir}/predictions.json")
        self.core = PredictionCore()
        self.world_memory = WorldMemory(persist_path=f"{persist_dir}/world_memory.json")
        self.beliefs = BeliefEngine(persist_path=f"{persist_dir}/beliefs.json")
        self.decisions = DecisionMemory(persist_path=f"{persist_dir}/decisions.json")
        self.causal_graph = CausalGraph()
        self.scenario_planner = ScenarioPlanner()
        from server.systems.prediction.self_evaluator import SelfEvaluator
        self.self_evaluator = SelfEvaluator(persist_path=f"{persist_dir}/self_eval.json")
        from server.systems.prediction.meta_policy import MetaPolicy
        self.meta_policy = MetaPolicy()

    def predict_turn(self, features: Dict[str, float]) -> Dict[str, Any]:
        """Predict the next-turn trajectory from current features."""
        req = PredictionRequest(domain="conversation", entity="user_turn", features=features)
        out = self.core.predict(req)
        self.store.add(
            f"user turn outcome ~{out.value:.2f}",
            out.confidence,
            domain="conversation",
            value=out.value,
        )
        return {
            "value": out.value,
            "confidence": out.confidence,
            "uncertainty": out.uncertainty,
            "reasoning_trace": out.reasoning_trace,
            "forecast": self.core.predict_future({"value": out.value}, steps=3),
            "horizons": self.core.forecast_horizons({"value": out.value, "drift": out.value - 0.5}),
        }

    def governed_predict(self, features: Dict[str, float],
                         memory: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Predict→govern: run predict_turn() through the MetaPolicy gate
        (NEWPredictionPRT2 §"Meta-Policy"). Returns the raw prediction plus the
        PolicyDecision — REQUEST_MORE_DATA / CAUTION / ABSTAIN / ACCEPT — so
        callers know whether to act on, hedge, withhold, or extend the forecast."""
        pred = self.predict_turn(features)
        direction = (pred.get("horizons") or {}).get("direction", "stable")
        up = 0.75 if direction == "rising" else 0.1
        down = 0.75 if direction == "falling" else 0.1
        neutral = 0.75 if direction == "stable" else 0.2
        decision = self.meta_policy.decide(
            {
                "confidence": pred["confidence"],
                "uncertainty": pred["uncertainty"],
                "volatility": abs(pred.get("value", 0.5) - 0.5),
                "up": up, "down": down, "neutral": neutral,
            },
            memory=memory or [],
        )
        return {**pred, "policy": decision.to_dict()}

    def govern_forecast(self, forecast: Dict[str, Any],
                        memory: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Gate an already-computed forecast dict (value/confidence/uncertainty
        + optional direction patterns) through the MetaPolicy."""
        decision = self.meta_policy.decide(forecast, memory=memory)
        return {"forecast": forecast, "policy": decision.to_dict()}

    def causal_chains(self, start_node: str) -> List[Dict[str, Any]]:
        return self.causal_graph.propagate(start_node)

    def evaluate_actions(self, candidates: List[Dict[str, Any]],
                         state: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
        """Predict→select→act (NEWPredictionPRT2 §5/§6 + "predict(state,
        candidate_action) → Future A/B/C").

        Scores each candidate action/reply against the current cognitive state
        and returns them ranked by predicted outcome. Higher predicted valence /
        trust shift + lower uncertainty + alignment with a known-good plan wins.

        Candidate shape (dict): {"id", "description", "style" or "action",
                                 "intent"} — anything with an id + description.
        The evaluator also consults DecisionMemory so past outcomes of similar
        decisions influence the ranking (Learning Router §Phase 3.5).
        """
        state = state or {
            "valence": getattr(self, "_last_valence", 0.0),
            "trust": getattr(self, "_last_trust", 0.5),
        }
        results: List[Dict[str, Any]] = []
        for cand in candidates:
            # Predictive delta: estimate the outcome of this action as a
            # (value, confidence, uncertainty) forecast from its intent/style.
            intent = str(cand.get("intent") or cand.get("style") or cand.get("action") or cand.get("description", "")).lower()
            _BIAS = {
                "de-escalate": 0.35, "soothe": 0.3, "support": 0.25,
                "soothing": 0.3, "calm": 0.3, "reassure": 0.25,
                "playful": 0.05, "tease": 0.05, "light": 0.05,
                "assert": -0.2, "assertive": -0.2, "challenge": -0.25,
                "reflective": 0.15, "deep": 0.15,
                "neutral": 0.0, "assist": 0.15, "help": 0.15,
                "research": 0.1, "clarify": 0.1,
            }
            intent_bias = next((v for k, v in _BIAS.items() if k in intent), 0.0)
            base_val = float(state.get("valence", 0.0))
            trust = float(state.get("trust", 0.5))
            predicted_value = max(0.0, min(1.0, (base_val + 1) / 2 + intent_bias))
            confidence = max(0.3, min(0.95, 0.5 + abs(intent_bias) * 1.5 + (trust - 0.5) * 0.4))
            uncertainty = 1.0 - confidence

            # Prior from DecisionMemory: reuse the outcome of similar past
            # decisions (Learning Router / ExperienceStore).
            prior_reward = self.decisions.retrieve_similar({"intent": intent}, top_k=1)
            prior = float(prior_reward[0]["reward"]) if prior_reward else 0.0

            score = (predicted_value * 0.5 + confidence * 0.2
                     + (prior + 0.5) * 0.2 + (1.0 - uncertainty) * 0.1)
            results.append({
                "id": cand.get("id", ""),
                "description": cand.get("description", ""),
                "intent": intent,
                "predicted_value": round(predicted_value, 3),
                "confidence": round(confidence, 3),
                "uncertainty": round(uncertainty, 3),
                "prior_reward": round(prior, 3),
                "score": round(score, 3),
            })
        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    def select_action(self, candidates: List[Dict[str, Any]],
                      state: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """Pick the best candidate by predicted outcome (predict→select→act)."""
        ranked = self.evaluate_actions(candidates, state=state)
        return ranked[0] if ranked else {}

    def multi_scenario(self, candidates: List[Dict[str, Any]],
                       state: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """Multi-Scenario Planning (NEWPredictionPRT2 §"6. Multi-Scenario
        Planning"): instead of a single chosen action, produce Best / Expected
        / Worst branch trajectories around the predicted outcome of the best
        candidate, so the brain can plan contingencies for each branch.

        Returns {"chosen", "expected", "best", "worst", "plan"}.
        """
        chosen = self.select_action(candidates, state=state)
        base = ScenarioPlanner().plan(
            value=float(chosen.get("predicted_value", 0.5)) if chosen else 0.5,
            confidence=float(chosen.get("confidence", 0.5)) if chosen else 0.3,
        )
        out = {
            "chosen": chosen,
            "expected": base["scenarios"]["expected"],
            "best": base["scenarios"]["best"],
            "worst": base["scenarios"]["worst"],
            "plan": base,
        }
        # Also write the scenario run into the prediction store so it is
        # verifiable later (the closed loop can check which branch realized).
        try:
            self.store.add(
                f"multi-scenario around '{chosen.get('id', 'action')}'",
                base["confidence"], domain="scenario",
            )
        except Exception:
            pass
        return out

    def verify_prediction(self, prediction_id: str, actual_value: float,
                          *, outcome: Optional[str] = None) -> Dict[str, Any]:
        """Quantitative verification (NEWPredictionPRT2 §"3. Self Evaluation
        Engine"): record the ACTUAL numeric value for a stored prediction and
        feed the error magnitude into the SelfEvaluator learning loop.

        Returns the verification result + the learning-loop metrics.
        """
        entry = None
        for p in self.store.predictions:
            if p["id"] == prediction_id:
                entry = p
                break
        if entry is None:
            return {"error": "unknown prediction"}

        pred = entry.get("predicted_value")
        domain = entry.get("domain", "general")
        if pred is None:
            # No numeric prediction stored — fall back to binary verification.
            self.store.verify(prediction_id, outcome or "resolved",
                              correct=actual_value >= 0.5)
            return {"prediction_id": prediction_id, "quantitative": False,
                    "self_eval": self.self_evaluator.metrics()}

        correct = (pred >= 0.5 and actual_value >= 0.5) or (pred < 0.5 and actual_value < 0.5)
        self.store.verify(prediction_id, outcome or "resolved", correct=correct,
                          actual_value=actual_value)
        error = self.self_evaluator.record(pred, actual_value, domain=domain)
        return {
            "prediction_id": prediction_id,
            "quantitative": True,
            "predicted": pred,
            "actual": round(float(actual_value), 4),
            "error": round(error, 4),
            "correct": correct,
            "domain": domain,
            "self_eval": self.self_evaluator.metrics(),
        }

    def self_eval_metrics(self) -> Dict[str, Any]:
        """Learning-loop + quantitative error summary for the dashboard."""
        return self.self_evaluator.metrics()

    def learn_forecast(self) -> Dict[str, Any]:
        """Train the learned forecast head on the store's verified
        (predicted_value, confidence) → actual_value transitions. Call it after
        verification passes so predict_future() gets genuinely learned."""

        trained = self.core.forecast_model.learn_from_verification(self.store.predictions)
        return {"trained": trained, "forecast_model": self.core.forecast_model.state()}

    def assess_alerts(self, *, user_state: Optional[Dict[str, Any]] = None,
                      horizon_days: float = 30) -> List[Dict[str, Any]]:
        """Proactive notify chain (NEWPredictionPRT2 §11/§Proactive + "impact →
        relevance → notify"): scan recent world events, score each by impact
        (magnitude of the signal) and relevance to the current user state, and
        surface the top actionable events so the daemon/brain can proactively
        raise them instead of waiting for the next user turn.

        An event is "actionable" when its relevance exceeds a threshold — the
        caller decides whether to actually notify (e.g. only raise truly
        high-impact, high-relevance events unprompted).
        """
        user_state = user_state or {
            "valence": getattr(self, "_last_valence", 0.0),
            "trust": getattr(self, "_last_trust", 0.5),
        }
        recent = self.world_memory.recent(days=horizon_days)
        if not recent:
            return []
        current_valence = float(user_state.get("valence", 0.0))
        alerts = []
        for event in recent[-50:]:
            domain = str(event.get("domain", "general"))
            valence = float(event.get("valence", 0.0))
            # Impact: how far the event's signal moved from neutral.
            impact = min(1.0, abs(valence))
            # Relevance: alignment with the user's current emotional direction.
            relevance = 1.0 if current_valence * valence >= 0 else abs(current_valence - valence)
            relevance = min(1.0, max(0.0, relevance))
            alert_score = impact * 0.6 + relevance * 0.4
            alerts.append({
                "domain": domain,
                "entity": event.get("entity", "user"),
                "impact": round(impact, 3),
                "relevance": round(relevance, 3),
                "score": round(alert_score, 3),
                "valence": round(valence, 3),
                "timestamp": event.get("timestamp"),
                "actionable": alert_score >= 0.5,
            })
        alerts.sort(key=lambda a: a["score"], reverse=True)
        return alerts

    def snapshot(self) -> Dict[str, Any]:
        return {
            "predictions": self.store.predictions[-20:],
            "accuracy": self.store.accuracy(),
            "unverified": len(self.store.unverified()),
            "beliefs": {k: v["confidence"] for k, v in self.beliefs.beliefs.items()},
            "recent_events": self.world_memory.recent(days=7),
            "calibration": self.core.calibration_state(),
        }


# ── Shared singleton ───────────────────────────────────────────────────────────

_engine: Optional[PredictionEngine] = None


def get_prediction_engine() -> PredictionEngine:
    """Shared PredictionEngine so the router, brain, and daemon all read/write
    one persisted store instead of each constructing a disjoint in-memory one."""
    global _engine
    if _engine is None:
        _engine = PredictionEngine(persist_dir="./data/prediction")
    return _engine
