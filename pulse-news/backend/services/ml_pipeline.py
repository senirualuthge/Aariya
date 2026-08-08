from __future__ import annotations

import json
import logging
import math
import os
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import re

from db import db_cursor  # type: ignore

logger = logging.getLogger("pulse.ml")

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models")
os.makedirs(MODEL_DIR, exist_ok=True)

XGB_MODEL_PATH = os.path.join(MODEL_DIR, "trend_xgboost.json")
TFT_MODEL_PATH = os.path.join(MODEL_DIR, "trend_tft.pt")
ENSEMBLE_WEIGHTS_PATH = os.path.join(MODEL_DIR, "ensemble_weights.json")

_TRAINING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ml_training_samples (
    id          SERIAL PRIMARY KEY,
    article_id  TEXT,
    recorded_at TIMESTAMPTZ DEFAULT now(),
    velocity_1h    FLOAT, velocity_24h   FLOAT,
    novelty_score  FLOAT, source_credibility FLOAT,
    entity_count   FLOAT, importance     FLOAT,
    engagement_rate FLOAT, source_diversity FLOAT,
    burst_score    FLOAT, sentiment      FLOAT,
    target_importance FLOAT, target_is_breaking BOOLEAN,
    label_window_hours INT DEFAULT 24, model_used TEXT
);
"""


class TrendForecaster:
    def __init__(self):
        self.is_loaded = False
        self._xgboost_model: Any = None
        self._tft_model: Any = None
        self._ensemble_weights = {"xgboost": 0.4, "tft": 0.4, "embedding_novelty": 0.2}
        self._init_store()
        self._load_ensemble_weights()

    @staticmethod
    def _init_store():
        try:
            with db_cursor() as cur:
                cur.execute(_TRAINING_TABLE_SQL)
        except Exception as exc:
            logger.debug("[ML] Training table init: %s", exc)

    def load_models(self):
        self._try_load_xgboost()
        self._try_load_tft()
        self.is_loaded = True
        logger.info("[ML] Engine ready (xgboost=%s, tft=%s)", bool(self._xgboost_model), bool(self._tft_model))

    def _try_load_xgboost(self):
        if os.path.exists(XGB_MODEL_PATH):
            try:
                import xgboost as xgb
                self._xgboost_model = xgb.Booster()
                self._xgboost_model.load_model(XGB_MODEL_PATH)
                logger.info("[ML] Loaded XGBoost from %s", XGB_MODEL_PATH)
            except Exception as exc:
                logger.warning("[ML] XGBoost load failed: %s", exc)
                self._xgboost_model = None

    def _try_load_tft(self):
        if os.path.exists(TFT_MODEL_PATH):
            try:
                import torch
                self._tft_model = torch.load(TFT_MODEL_PATH, map_location="cpu")
                self._tft_model.eval()
                logger.info("[ML] Loaded TFT from %s", TFT_MODEL_PATH)
            except Exception as exc:
                logger.warning("[ML] TFT load failed: %s", exc)
                self._tft_model = None

    def _load_ensemble_weights(self):
        if os.path.exists(ENSEMBLE_WEIGHTS_PATH):
            try:
                with open(ENSEMBLE_WEIGHTS_PATH) as f:
                    self._ensemble_weights = json.load(f)
            except Exception as exc:
                logger.debug("[ML] Failed to load ensemble weights: %s", exc)

    def _save_ensemble_weights(self):
        try:
            with open(ENSEMBLE_WEIGHTS_PATH, "w") as f:
                json.dump(self._ensemble_weights, f)
        except Exception as exc:
            logger.debug("[ML] Ensemble weights save failed: %s", exc)

    def extract_features(self, article: Dict[str, Any], history: List[Dict[str, Any]]) -> Dict[str, float]:
        cat = article.get("category", "other") or "other"
        now = datetime.now(timezone.utc)
        window_1h = 0
        window_24h = 0
        if history:
            for h in history:
                h_cat = h.get("category", "other") or "other"
                if h_cat != cat:
                    continue
                ts = h.get("ingested_at") or h.get("published_at", "")
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except Exception:
                        continue
                if ts and isinstance(ts, datetime):
                    age_hours = (now - ts).total_seconds() / 3600
                    if age_hours <= 1:
                        window_1h += 1
                    if age_hours <= 24:
                        window_24h += 1

        imp = article.get("importance", 5) or 5
        entities: List[str] = article.get("key_entities", [])
        source_div = self._source_diversity(cat)
        burst = self._compute_burst(cat)

        return {
            "velocity_1h": float(window_1h),
            "velocity_24h": float(window_24h),
            "novelty_score": self._compute_novelty(article, history),
            "source_credibility": self._source_credibility(article.get("url", "")),
            "entity_count": float(len(entities)),
            "importance": float(imp),
            "engagement_rate": float(article.get("engagement_score", 0)),
            "source_diversity": source_div,
            "burst_score": burst,
            "sentiment": float(article.get("sentiment", 0)),
        }

    def predict_importance(self, features: Dict[str, float]) -> float:
        xgb_pred = self._xgboost_predict(features)
        tft_pred = self._tft_predict(features)
        embedding_novelty = features.get("novelty_score", 0.5)

        w_x = self._ensemble_weights.get("xgboost", 0.4)
        w_t = self._ensemble_weights.get("tft", 0.4)
        w_e = self._ensemble_weights.get("embedding_novelty", 0.2)

        ensemble = w_x * xgb_pred + w_t * tft_pred + w_e * embedding_novelty
        return round(min(1.0, max(0.0, ensemble)), 4)

    def predict_breaking_probability(self, features: Dict[str, float]) -> float:
        importance = self.predict_importance(features)
        burst = features.get("burst_score", 0)
        velocity = features.get("velocity_1h", 0)
        diversity = features.get("source_diversity", 0.5)
        trend_accel = burst * 0.3 + min(1.0, velocity / 10.0) * 0.3

        raw_prob = importance + trend_accel + diversity * 0.2
        prob = 1.0 / (1.0 + math.exp(-5.0 * (raw_prob - 0.5)))
        return round(min(1.0, max(0.0, prob)), 4)

    def _xgboost_predict(self, features: Dict[str, float]) -> float:
        if self._xgboost_model is not None:
            try:
                import numpy as np
                import xgboost as xgb
                fvec = np.array([[
                    features.get("velocity_1h", 0),
                    features.get("velocity_24h", 0),
                    features.get("novelty_score", 0.5),
                    features.get("source_credibility", 0.6),
                    features.get("entity_count", 0),
                    features.get("importance", 5),
                    features.get("engagement_rate", 0),
                    features.get("source_diversity", 0.5),
                    features.get("burst_score", 0),
                    features.get("sentiment", 0),
                ]], dtype=np.float32)
                return min(1.0, max(0.0, float(self._xgboost_model.predict(xgb.DMatrix(fvec))[0])))
            except Exception as exc:
                logger.debug("[ML] XGBoost predict failed: %s", exc)
        return self._online_regression_predict(features)

    def _tft_predict(self, features: Dict[str, float]) -> float:
        if self._tft_model is not None:
            try:
                import torch
                fvec = torch.tensor([[
                    features.get("velocity_1h", 0),
                    features.get("velocity_24h", 0),
                    features.get("novelty_score", 0.5),
                    features.get("source_credibility", 0.6),
                    features.get("entity_count", 0),
                    features.get("importance", 5),
                ]], dtype=torch.float32)
                with torch.no_grad():
                    pred = self._tft_model(fvec).item()
                return min(1.0, max(0.0, float(pred)))
            except Exception as exc:
                logger.debug("[ML] TFT predict failed: %s", exc)
        return self._online_regression_predict(features)

    def _online_regression_predict(self, features: Dict[str, float]) -> float:
        FEATURE_KEYS = ["velocity_1h","velocity_24h","novelty_score","source_credibility",
                        "entity_count","importance","engagement_rate","source_diversity",
                        "burst_score","sentiment"]
        try:
            with db_cursor() as cur:
                cur.execute(
                    """SELECT """ + ", ".join(
                        f"AVG({k}) as avg_{k}, STDDEV({k}) as std_{k}, "
                        f"CORR({k}, target_importance) as corr_{k}"
                        for k in FEATURE_KEYS
                    ) + """, AVG(target_importance) as avg_target, COUNT(*) as n
                    FROM ml_training_samples WHERE target_importance IS NOT NULL"""
                )
                row = cur.fetchone()
                if not row:
                    return self._fallback_predict(features)
                n = int(row["n"]) if row else 0
                if n >= 30:
                    weights = {}
                    total_abs = 0.0
                    for k in FEATURE_KEYS:
                        corr = row.get(f"corr_{k}") or 0.0
                        weights[k] = abs(corr)
                        total_abs += abs(corr)
                    if total_abs > 0:
                        pred = 0.0
                        avg_target = float(row["avg_target"] or 0.5)
                        for k in FEATURE_KEYS:
                            w = weights[k] / total_abs
                            fv = features.get(k, 0.0)
                            avg_k = float(row.get(f"avg_{k}") or 0.0)
                            std_k = float(row.get(f"std_{k}") or 1.0)
                            if std_k < 0.001:
                                std_k = 1.0
                            contribution = w * (fv - avg_k) / std_k if n > 0 else 0.0
                            pred += contribution
                        return min(1.0, max(0.0, avg_target + pred))
        except Exception as exc:
            logger.debug("[ML] Online regression predict failed: %s", exc)
        return self._fallback_predict(features)

    def _fallback_predict(self, features: Dict[str, float]) -> float:
        v1h = features.get("velocity_1h", 0)
        v24h = features.get("velocity_24h", 0)
        novelty = features.get("novelty_score", 0.5)
        credibility = features.get("source_credibility", 0.6)
        entity_count = features.get("entity_count", 0)
        base_imp = features.get("importance", 5)
        burst = features.get("burst_score", 0)

        v_norm = min(1.0, (v1h * 0.6 + v24h * 0.4) / 20.0)
        e_norm = min(1.0, entity_count / 5.0)

        return round(min(1.0, max(0.0,
            0.25 * v_norm + 0.20 * novelty + 0.15 * credibility +
            0.10 * e_norm + 0.10 * (base_imp / 10.0) + 0.20 * burst
        )), 4)

    def collect_training_samples(self, articles: List[Dict[str, Any]]):
        inserted = 0
        for a in articles:
            features = self.extract_features(a, [])
            try:
                with db_cursor() as cur:
                    cur.execute(
                        """INSERT INTO ml_training_samples
                        (article_id, velocity_1h, velocity_24h, novelty_score,
                         source_credibility, entity_count, importance,
                         engagement_rate, source_diversity, burst_score, sentiment)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT DO NOTHING""",
                        (a.get("id"), features["velocity_1h"], features["velocity_24h"],
                         features["novelty_score"], features["source_credibility"],
                         features["entity_count"], features["importance"],
                         features["engagement_rate"], features["source_diversity"],
                         features["burst_score"], features["sentiment"]),
                    )
                    if cur.rowcount:
                        inserted += 1
            except Exception as exc:
                logger.debug("[ML] Sample skipped: %s", exc)
        if inserted:
            logger.debug("[ML] Collected %d samples", inserted)

    def _backfill_labels(self, window_hours: int = 24):
        try:
            with db_cursor() as cur:
                cur.execute(
                    """UPDATE ml_training_samples t SET
                    target_importance = (SELECT AVG(a.importance::float) FROM articles a
                        WHERE a.ingested_at BETWEEN t.recorded_at AND t.recorded_at + INTERVAL '%s hours'
                        AND a.importance IS NOT NULL),
                    target_is_breaking = EXISTS (SELECT 1 FROM articles a
                        WHERE a.ingested_at BETWEEN t.recorded_at AND t.recorded_at + INTERVAL '%s hours'
                        AND a.importance >= 8)
                    WHERE t.target_importance IS NULL
                    AND t.recorded_at < now() - INTERVAL '%s hours'""",
                    (window_hours, window_hours, window_hours),
                )
                if cur.rowcount:
                    logger.info("[ML] Backfilled %d labels", cur.rowcount)
        except Exception as exc:
            logger.debug("[ML] Label backfill skipped: %s", exc)

    async def train_models(self):
        self._backfill_labels()
        await self._train_xgboost()
        await self._train_tft()
        self._optimize_ensemble_weights()

    async def _train_xgboost(self):
        try:
            import numpy as np
            import xgboost as xgb
            from sklearn.metrics import mean_absolute_error, r2_score

            with db_cursor() as cur:
                cur.execute(
                    """SELECT velocity_1h, velocity_24h, novelty_score,
                    source_credibility, entity_count, importance,
                    engagement_rate, source_diversity, burst_score, sentiment,
                    target_importance FROM ml_training_samples
                    WHERE target_importance IS NOT NULL ORDER BY recorded_at ASC"""
                )
                rows = cur.fetchall()

            if not rows or len(rows) < 50:
                logger.info("[ML] Not enough XGB samples (%d)", len(rows) if rows else 0)
                return

            X, y = [], []
            for r in rows:
                X.append([float(r[k]) for k in
                    ("velocity_1h","velocity_24h","novelty_score","source_credibility",
                     "entity_count","importance","engagement_rate","source_diversity",
                     "burst_score","sentiment")])
                y.append(float(r["target_importance"]))

            X_arr, y_arr = np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)
            split = int(len(X_arr) * 0.8)
            X_train, X_test = X_arr[:split], X_arr[split:]
            y_train, y_test = y_arr[:split], y_arr[split:]

            dtrain = xgb.DMatrix(X_train, label=y_train)
            dtest = xgb.DMatrix(X_test, label=y_test)

            model = xgb.train({
                "objective": "reg:squarederror", "max_depth": 6,
                "learning_rate": 0.1, "subsample": 0.8,
                "colsample_bytree": 0.8, "min_child_weight": 3,
                "eval_metric": "rmse", "seed": 42,
            }, dtrain, num_boost_round=200,
               evals=[(dtrain, "train"), (dtest, "test")],
               early_stopping_rounds=20, verbose_eval=False)

            model.save_model(XGB_MODEL_PATH)
            self._xgboost_model = model
            y_pred = model.predict(dtest)
            logger.info("[ML] XGBoost trained — MAE: %.4f, R2: %.4f (n=%d)",
                       mean_absolute_error(y_test, y_pred), r2_score(y_test, y_pred), len(y_train)) # type: ignore
        except ImportError:
            logger.info("[ML] xgboost not installed")
        except Exception as exc:
            logger.error(f"[ML] XGBoost training failed: {exc}")

    async def _train_tft(self):
        try:
            import torch
            import torch.nn as nn
            import numpy as np

            with db_cursor() as cur:
                cur.execute(
                    """SELECT velocity_1h, velocity_24h, novelty_score,
                    source_credibility, entity_count, importance, target_importance
                    FROM ml_training_samples
                    WHERE target_importance IS NOT NULL ORDER BY recorded_at ASC"""
                )
                rows = cur.fetchall()

            if not rows or len(rows) < 30:
                logger.info("[ML] Not enough TFT samples (%d)", len(rows) if rows else 0)
                return

            X, y = [], []
            for r in rows:
                X.append([float(r[k]) for k in
                    ("velocity_1h","velocity_24h","novelty_score",
                     "source_credibility","entity_count","importance")])
                y.append(float(r["target_importance"]))

            X_t, y_t = torch.tensor(X, dtype=torch.float32), torch.tensor(y, dtype=torch.float32)
            split = int(len(X_t) * 0.8)

            model = nn.Sequential(
                nn.Linear(6, 32), nn.ReLU(), nn.Dropout(0.2),
                nn.Linear(32, 16), nn.ReLU(),
                nn.Linear(16, 8), nn.ReLU(),
                nn.Linear(8, 1), nn.Sigmoid(),
            )

            opt = torch.optim.Adam(model.parameters(), lr=0.01)
            loss_fn = nn.MSELoss()

            for epoch in range(100):
                opt.zero_grad()
                pred = model(X_t[:split])
                loss = loss_fn(pred.squeeze(), y_t[:split])
                loss.backward()
                opt.step()

            torch.save(model, TFT_MODEL_PATH)
            self._tft_model = model
            with torch.no_grad():
                val_loss = loss_fn(model(X_t[split:]).squeeze(), y_t[split:]).item()
            logger.info("[ML] TFT trained — val_loss: %.4f (n=%d)", val_loss, split)
        except ImportError:
            logger.info("[ML] torch not installed — TFT skipped")
        except Exception as exc:
            logger.error(f"[ML] TFT training failed: {exc}")

    def _optimize_ensemble_weights(self):
        try:
            import numpy as np
            from sklearn.metrics import mean_absolute_error

            with db_cursor() as cur:
                cur.execute(
                    """SELECT velocity_1h, velocity_24h, novelty_score,
                    source_credibility, entity_count, importance,
                    engagement_rate, source_diversity, burst_score, sentiment,
                    target_importance FROM ml_training_samples
                    WHERE target_importance IS NOT NULL ORDER BY recorded_at ASC"""
                )
                rows = cur.fetchall()

            if not rows or len(rows) < 20:
                return

            best_mae = float("inf")
            best_w = self._ensemble_weights.copy()

            for _ in range(500):
                w_x = np.random.uniform(0.1, 0.6)
                w_t = np.random.uniform(0.1, 0.6)
                w_e = 1.0 - w_x - w_t
                if w_e < 0.05:
                    continue

                errors = []
                for r in rows[-50:]:
                    feats = {k: float(r[k]) for k in
                        ("velocity_1h","velocity_24h","novelty_score","source_credibility",
                         "entity_count","importance","engagement_rate","source_diversity",
                         "burst_score","sentiment")}
                    xgb_p = self._xgboost_predict(feats) if self._xgboost_model else self._online_regression_predict(feats)
                    tft_p = self._tft_predict(feats) if self._tft_model else self._online_regression_predict(feats)
                    ensemble = w_x * xgb_p + w_t * tft_p + w_e * feats.get("novelty_score", 0.5)
                    errors.append(abs(ensemble - float(r["target_importance"])))

                mae = np.mean(errors)
                if mae < best_mae:
                    best_mae = mae
                    best_w = {"xgboost": w_x, "tft": w_t, "embedding_novelty": w_e}

            self._ensemble_weights = best_w
            self._save_ensemble_weights()
            logger.info("[ML] Ensemble weights optimized: %s (MAE=%.4f)", best_w, best_mae)
        except Exception as exc:
            logger.debug("[ML] Ensemble optimization skipped: %s", exc)

    def compute_trend_signal(self, category: str) -> Dict[str, Any]:
        with db_cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) as cnt FROM articles
                WHERE category = %s AND ingested_at > now() - INTERVAL '1 hour'""",
                (category,),
            )
            row1 = cur.fetchone()
            recent = row1["cnt"] if row1 else 0
            cur.execute(
                """SELECT COUNT(*) as cnt FROM articles
                WHERE category = %s AND ingested_at BETWEEN now() - INTERVAL '2 hours' AND now() - INTERVAL '1 hour'""",
                (category,),
            )
            row2 = cur.fetchone()
            prev = row2["cnt"] if row2 else 1
            cur.execute(
                """SELECT COUNT(DISTINCT source_id) as src FROM articles
                WHERE category = %s AND ingested_at > now() - INTERVAL '1 hour'""",
                (category,),
            )
            row3 = cur.fetchone()
            diversity = row3["src"] if row3 else 0

        velocity = recent - prev
        burst_ratio = recent / max(prev, 1)
        trend_score = self._online_regression_predict({
            "velocity_1h": float(recent), "velocity_24h": 0,
            "novelty_score": 0.5, "source_credibility": 0.6,
            "entity_count": 0, "importance": 5,
            "engagement_rate": 0, "source_diversity": min(1.0, diversity / 5.0),
            "burst_score": min(1.0, (burst_ratio - 1.0) / 3.0), "sentiment": 0,
        })

        return {
            "category": category,
            "recent_mentions": recent,
            "velocity": float(velocity),
            "burst_ratio": round(burst_ratio, 2),
            "source_diversity": diversity,
            "trend_score": trend_score,
            "status": "emerging" if burst_ratio > 2.0 else "peaking" if burst_ratio > 1.5 else "stable" if burst_ratio > 0.8 else "decaying",
        }

    @staticmethod
    def _compute_novelty(article: Dict[str, Any], history: List[Dict[str, Any]]) -> float:
        entities: List[str] = article.get("key_entities", [])
        if not entities or not history:
            return 0.7
        known_entities: set[str] = set()
        for h in history:
            he = h.get("key_entities", [])
            known_entities.update(he)
        overlap = sum(1 for e in entities if e in known_entities)
        if len(entities) == 0:
            return 0.7
        return 1.0 - (overlap / len(entities))

    @staticmethod
    def _source_credibility(url: str) -> float:
        _trusted_raw = os.getenv("PULSE_TRUSTED_DOMAINS", "")
        _trusted: dict[str, float] = {}
        if _trusted_raw:
            for pair in _trusted_raw.split(","):
                if ":" in pair:
                    d, s = pair.rsplit(":", 1)
                    try:
                        _trusted[d.strip()] = float(s)
                    except ValueError:
                        pass
        if not _trusted:
            _trusted = {
                "reuters.com": 0.95, "apnews.com": 0.95, "bbc.com": 0.92,
                "nytimes.com": 0.90, "wsj.com": 0.90, "bloomberg.com": 0.88,
                "economist.com": 0.90, "theguardian.com": 0.85, "npr.org": 0.85,
                "washingtonpost.com": 0.88,
            }
        for domain, score in _trusted.items():
            if domain in url:
                return score
        return float(os.getenv("PULSE_DEFAULT_CREDIBILITY", "0.60"))

    @staticmethod
    def _source_diversity(category: str) -> float:
        try:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT COUNT(DISTINCT source_id) FROM articles WHERE category = %s AND ingested_at > now() - INTERVAL '1 hour'",
                    (category,),
                )
                row = cur.fetchone()
                count = row["count"] if row else 0
            return min(1.0, count / 5.0)
        except Exception as exc:
            logger.debug("[ML] Source diversity query failed for %s: %s", category, exc)
            return 0.5

    @staticmethod
    def _compute_burst(category: str) -> float:
        try:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM articles WHERE category = %s AND ingested_at > now() - INTERVAL '1 hour'",
                    (category,),
                )
                row1 = cur.fetchone()
                recent = row1["count"] if row1 else 0
                cur.execute(
                    "SELECT COUNT(*) FROM articles WHERE category = %s AND ingested_at BETWEEN now() - INTERVAL '2 hours' AND now() - INTERVAL '1 hour'",
                    (category,),
                )
                row2 = cur.fetchone()
                prev = row2["count"] if row2 else 1
            if prev == 0:
                return 0.0
            return min(1.0, max(0.0, (recent / prev - 1.0) / 3.0))
        except Exception as exc:
            logger.debug("[ML] Burst compute failed for %s: %s", category, exc)
            return 0.0


forecaster = TrendForecaster()
