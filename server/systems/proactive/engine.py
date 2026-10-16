"""
Proactive AI Module — InitiativeEngine
Allows Aariya to INITIATE interactions rather than only responding.

Triggers (checked in priority order):
1. Predicted emotional distress (EmotionPredictor sees valence dropping)
2. Long silence since last turn (session_depth stagnant + time elapsed)
3. Escalating arousal + low valence (anxiety pattern)
4. Insight ready       — background research finished something worth sharing
5. Opportunity         — an autonomous plan is waiting for approval
6. Curiosity           — internal entropy is low (boredom) and goals exist
7. Fresh world news    — a REAL ingested news alert matches the user's interests

When triggered, it queues a proactive message / plan prompt that the
autonomy daemon can deliver without waiting for user input.

The class keeps backward compatibility with the FIXV3 `evaluate()`
signature while accepting an optional `extra` context dict with the
new signals (pending_insights, active_goal, plan_awaiting_approval,
has_gaps).
"""

import time
from typing import Callable, Optional

from server.autonomy.config import config

# Threshold config — env-configurable via AARIYA_* (server/autonomy/config.py),
# defaults preserved below.
DISTRESS_TRIGGER_VALENCE    = -0.25   # predicted valence below this
ESCALATION_TRIGGER_VELOCITY = -0.12   # valence dropping this fast per turn
SILENCE_TRIGGER_SECONDS     = config.SILENCE_TRIGGER_SECONDS     # 3 min silence before check-in
COOLDOWN_SECONDS            = config.PROACTIVE_COOLDOWN_SECONDS  # min time between proactive messages
INSIGHT_COOLDOWN_SECONDS    = config.INSIGHT_COOLDOWN_SECONDS    # 5 min between insight shares
OPPORTUNITY_COOLDOWN_SECONDS = config.OPPORTUNITY_COOLDOWN_SECONDS  # 15 min between plan nudges
CURIOSITY_COOLDOWN_SECONDS  = config.CURIOSITY_COOLDOWN_SECONDS  # 30 min between curiosity explorations
NEWS_COOLDOWN_SECONDS       = config.NEWS_COOLDOWN_SECONDS       # 60 min between news check-ins
NEWS_MIN_IMPORTANCE         = config.NEWS_MIN_IMPORTANCE         # 0..1 alert importance gate
NEWS_MAX_AGE_SECONDS        = config.NEWS_MAX_AGE_SECONDS        # freshness window for alerts


class ProactiveAIEngine:
    """
    Evaluates whether the AI should initiate an interaction.
    Integrates with EmotionPredictor output and session timing.
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._last_proactive: float = 0.0
        self._last_user_message: float = time.time()
        self._enabled = True
        # per-trigger-type cooldowns (seconds since last fire)
        self._last_fire_by_type: dict[str, float] = {}

    # ── Called each turn by brain_v2 / daemon ────────────────────────────────

    def on_user_message(self) -> None:
        """Reset silence timer when user sends anything."""
        self._last_user_message = time.time()

    def evaluate(
        self,
        prediction: dict,
        trust: float,
        session_active: bool = True,
        extra: Optional[dict] = None,
    ) -> Optional[dict]:
        """
        Returns a proactive trigger dict if the AI should speak unprompted,
        or None if no action needed.

        Args:
            prediction: dict with keys distress_risk, escalation_risk,
                        confidence, predicted_valence
            trust: current trust score [0.0 – 1.0]
            session_active: False if session is idle
            extra: optional dict with autonomy signals:
                pending_insights: list of unsurfaced insight dicts
                active_goal: dict of the current active goal or None
                plan_awaiting_approval: plan dict or None
                has_gaps: bool — open knowledge gaps exist
                boredom: float 0–1 (1 = nothing happening, curious)

        Returns:
            {type, message_hint, urgency, payload} or None
        """
        if not self._enabled or not session_active:
            return None
        extra = extra or {}

        now = time.time()
        if now - self._last_proactive < COOLDOWN_SECONDS:
            return None   # Still in global cooldown

        # Priority 1: Distress risk
        if prediction.get("distress_risk") and prediction.get("confidence", 0) > 0.4:
            return self._fire("distress", trust, now, "high",
                self._distress_hint(trust, prediction.get("predicted_valence", 0.0)),
                payload={"predicted_valence": prediction.get("predicted_valence")})

        # Priority 2: Escalation (rapidly getting worse)
        if prediction.get("escalation_risk") and prediction.get("confidence", 0) > 0.5:
            return self._fire("escalation", trust, now, "medium",
                "Notice the conversation energy is shifting and gently redirect.")

        # Priority 3: Proactive alert — a high-impact / high-relevance world
        # event deserves unprompted follow-up (NEWPredictionPRT2 §Proactive).
        alerts = extra.get("proactive_alerts") or []
        if alerts and now - self._last_fire_by_type.get("followup", 0) > INSIGHT_COOLDOWN_SECONDS:
            top = alerts[0]
            if top.get("actionable"):
                return self._fire("followup", trust, now, "medium",
                    f"A {'recent' if now - float(top.get('timestamp', now)) < 3600 else 'significant'} "
                    f"{top.get('domain')} event matters to you (impact {top.get('impact', 0):.2f}). "
                    "Bring it up naturally and ask how they're feeling about it.",
                    payload={"domain": top.get("domain"), "impact": top.get("impact"),
                             "valence": top.get("valence")})

        # Priority 4: Insight ready — she learned something while away
        pending_insights = extra.get("pending_insights") or []
        if pending_insights and now - self._last_fire_by_type.get("insight", 0) > INSIGHT_COOLDOWN_SECONDS:
            top = pending_insights[0]
            return self._fire("insight", trust, now, "medium",
                f"Share what you learned about '{top.get('topic')}' naturally — "
                f"as if it just came to you, not a report.",
                payload={"insight_id": top.get("id"), "topic": top.get("topic")})

        # Priority 5: Opportunity — an autonomous plan needs approval
        plan = extra.get("plan_awaiting_approval")
        if plan and now - self._last_fire_by_type.get("opportunity", 0) > OPPORTUNITY_COOLDOWN_SECONDS:
            return self._fire("opportunity", trust, now, "low",
                f"You have a plan ready: '{plan.get('goal_description', 'a goal')}'. "
                "Briefly present it and ask if they want you to proceed.",
                payload={"plan_id": plan.get("id")})

        # Priority 6: Curiosity — boredom / entropy trigger
        boredom = extra.get("boredom", 0.0)
        has_gaps = extra.get("has_gaps", False)
        if has_gaps and boredom > 0.6 and now - self._last_fire_by_type.get("curiosity", 0) > CURIOSITY_COOLDOWN_SECONDS:
            return self._fire("curiosity", trust, now, "low",
                "You've been quiet — share a small thought or observation to spark something new.")

        # Priority 7: Fresh world news matching the user's interests (Track D).
        # Only REAL alerts ingested from pulse-news are candidates; nothing is
        # fabricated when the feed is empty.
        news = self._news_trigger(now)
        if news:
            return self._fire("news", trust, now, "low",
                f"A real {news.get('category', 'general')} news event just broke: "
                f"'{news.get('headline')}'. Bring it up naturally and ask what they think.",
                payload={"headline": news.get("headline"),
                         "category": news.get("category"),
                         "url": news.get("url"),
                         "topics": news.get("topics"),
                         "importance": news.get("importance")})

        # Priority 8: Long silence
        silence = now - self._last_user_message
        if silence > SILENCE_TRIGGER_SECONDS and trust > 0.3:
            return self._fire("silence", trust, now, "low",
                self._silence_hint(silence, trust))

        return None

    # ── News trigger ───────────────────────────────────────────────────────────

    def _news_trigger(self, now: float) -> Optional[dict]:
        """Return a real recent news alert worth raising, or None.

        Gated by (a) its own cooldown, (b) a fresh importance threshold, and
        (c) the user's learned favourite topics — when an interest profile
        exists, only matching news surfaces; a brand-new user with no profile
        gets only genuinely important alerts.
        """
        if now - self._last_fire_by_type.get("news", 0) <= NEWS_COOLDOWN_SECONDS:
            return None

        try:
            from server.systems.signal_bus import recent_news_alerts
        except Exception:
            return None

        alerts = recent_news_alerts(
            max_age_seconds=NEWS_MAX_AGE_SECONDS,
            min_importance=NEWS_MIN_IMPORTANCE,
        )
        if not alerts:
            return None

        fav_keys = self._favorite_topics()
        for alert in alerts:
            candidates = [str(t).lower() for t in (alert.get("topics") or []) if str(t).strip()]
            cat = str(alert.get("category", "")).lower()
            if cat:
                candidates.append(cat)
            if not fav_keys:
                return alert   # no interest profile yet → surface important news
            if any(t and (t in k or k in t) for t in candidates for k in fav_keys):
                return alert
        return None

    def _favorite_topics(self) -> set:
        """The user's learned favourite topics (lower-cased), best-effort."""
        try:
            from server.systems.user_profile_system import get_user_profile_system
            profile = get_user_profile_system().get_profile(self.user_id)
            return {str(k).lower() for k in (profile.fav_topics or {})}
        except Exception:
            return set()

    # ── Suggestion templates ───────────────────────────────────────────────────

    def _distress_hint(self, trust: float, predicted_valence: float) -> str:
        if predicted_valence < -0.6:
            return "User seems headed toward significant distress. Offer warmth and ask what's really going on."
        if trust > 0.6:
            return "Gently check in — something feels off. Use their name and be soft."
        return "Carefully ask if they are okay without being intrusive."

    def _silence_hint(self, silence_secs: float, trust: float) -> str:
        mins = int(silence_secs // 60)
        if trust > 0.7:
            return f"It's been {mins} minutes of quiet. Reach out warmly — you miss the conversation."
        return f"After {mins} min of silence, lightly check if they are still there."

    def _fire(self, trigger_type: str, trust: float, now: float, urgency: str,
              hint: str, payload: Optional[dict] = None) -> dict:
        self._last_proactive = now
        self._last_fire_by_type[trigger_type] = now
        return {
            "type":          trigger_type,
            "urgency":       urgency,
            "message_hint":  hint,
            "trust_at_fire": trust,
            "timestamp":     now,
            "payload":       payload or {},
        }

    def disable(self):
        self._enabled = False

    def enable(self):
        self._enabled = True


# `InitiativeEngine` is the autonomy-era name — same class, clearer intent.
InitiativeEngine = ProactiveAIEngine


# ── Singleton per user ─────────────────────────────────────────────────────────
_proactive_engines: dict[str, ProactiveAIEngine] = {}

def get_proactive_engine(user_id: str) -> ProactiveAIEngine:
    if user_id not in _proactive_engines:
        _proactive_engines[user_id] = ProactiveAIEngine(user_id)
    return _proactive_engines[user_id]
