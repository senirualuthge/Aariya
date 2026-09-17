import asyncio
import logging
import re
import time
# BUG #3 FIX: Optional was missing — caused NameError on startup
from typing import Optional, Callable, Awaitable, List, Dict, Any

from server.protocol import MultimodalInput, MultimodalOutput, BrainState
from server.systems.self_awareness import SelfAwareness
from server.systems.theory_of_mind import TheoryOfMind
from server.systems.policy_router import PolicyRouter
from server.systems.emotion_behavior import EmotionBehavior
from server.systems.personality import PersonalitySystem
from server.systems.swarm.orchestrator import get_swarm_system
from server.systems.synoptic_aggregator import SynopticAggregator, SynopticState
from server.systems.synoptic_engine import SynopticEngine
from server.systems.narrative_engine import NarrativeEngine, create_event
from server.systems.narrative_arcs import NarrativeArcSystem, NarrativeArcEngine
from server.systems.meta_cognition import MetaCognitionEngine, compute_reflection
from server.systems.goals import GoalArbitrator
from server.systems.self_knowledge import get_self_knowledge
from server.systems.identity_kernel import get_identity_kernel
from server.systems.thoughts import ThoughtEngine
from server.systems.memory.conversation_log import ConversationLog
from server.systems.llm import get_llm
from server.systems.agent.grounding_validator import (
    grounding_validator,
    GroundingIssue,
)

logger = logging.getLogger("aariya.brain_v2")

# Canonical expression → emotion label mapping. `expression` (from
# EmotionBehavior.get_physical_mapping) is the discrete state sent in
# ai_response; this table expands it into the shared emotion vocabulary that
# clients tint on (Flutter orb: joy→gold, calm→cyan, sadness, fear, neutral).
# Kept at module level so tests can assert every label stays in the palette.
EXPRESSION_TO_EMOTION = {
    "joy": "joy",
    "smile": "calm",
    "concern": "fear",
    "sad": "sadness",
    "neutral": "neutral",
}


class BrainV2:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.self_awareness = SelfAwareness()
        self.theory_of_mind = TheoryOfMind()
        self.router = PolicyRouter()
        self.behavior = EmotionBehavior()
        self.personality = PersonalitySystem(user_id)
        self.swarm = get_swarm_system()
        self.synoptic_aggregator = SynopticAggregator()
        self.narrative_engine = NarrativeEngine()
        self.narrative_arcs = NarrativeArcSystem()
        self.narrative_arc_engine = NarrativeArcEngine()
        self.meta_cognition = MetaCognitionEngine()
        self.goal_arbitrator = GoalArbitrator()
        self.self_knowledge = get_self_knowledge()

        # Persistent long-term goal registry (NEWPredictionPRT2 §"1. Goal
        # Management Engine"): objectives survive restarts and are tracked with
        # progress + next_action, surfaced via the world-state tasks category.
        from server.systems.goal_manager import GoalManager
        self._goal_manager = GoalManager(persist_path=f"data/goals_{user_id}.json")

        # Doc (Agents Swarm Visualize §208): full synoptic pipeline orchestrator
        # (aggregate → smooth → velocity → narrative shock → influence → metrics).
        self.synoptic_engine = SynopticEngine(
            aggregator=self.synoptic_aggregator,
            narrative_engine=self.narrative_engine,
        )

        # ── Sentience modules ───────────────────────────────────────────────
        self.identity = get_identity_kernel()          # immutable core + mutable style
        self.thought_engine = ThoughtEngine()          # private inner monologue
        self.conversation = ConversationLog(user_id)   # durable conversational self

        # Continuity: resume emotional state from the last persisted snapshot
        # so a reconnect/restart doesn't reset her relationship to zero.
        last = self.conversation.last_state()
        if last:
            self.self_awareness.trust = last.get("trust", 0.5)
            self.self_awareness.valence = last.get("valence", 0.0)
            self.self_awareness.arousal = last.get("arousal", 0.0)
            self.self_awareness.attachment = last.get("attachment", 0.0)
            logger.debug("[BrainV2] Restored emotional continuity for %s "
                         "(trust=%.2f valence=%.2f)", user_id,
                         self.self_awareness.trust, self.self_awareness.valence)

        self.state = BrainState(
            personality=self.personality.get_current_personality()
        )
        self.self_awareness._last_trust = self.self_awareness.trust

        # FIXV5 grounding guard: residual contradictions between her reply and
        # the Layer 1 memories, surfaced to clients via output.meta["grounding"].
        self._last_grounding_issues: List[dict] = []

    async def process(
        self,
        input_data: MultimodalInput,
        on_token: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> MultimodalOutput:
        """Full cognitive pass over one user turn.

        `on_token` (optional async fn) is invoked with each streamed token of
        the reply so the WebSocket layer can push token-by-token text.
        """
        # 0. Proactive Security Scanning
        security_data = {
            "text": input_data.text or "",
            "metadata": input_data.metadata,
            "mobile": input_data.metadata.get("mobile", {}),
        }
        security_context = await self.swarm.run_security_agents(security_data)
        self.state.security = security_context

        risk_level = security_context.get("risk", {}).get("risk_level", "SAFE")
        security_issues = security_context.get("issues", [])

        # Threat detected → emotional stress spike
        if risk_level == "HIGH":
            self.self_awareness.arousal = max(0.9, self.self_awareness.arousal)
            self.self_awareness.valence = min(-0.8, self.self_awareness.valence)

        # Build security response prefix so AI explicitly warns the user
        security_prefix = ""
        if risk_level == "HIGH" and security_issues:
            top_issue = security_issues[0].get("issue", "security threat")
            security_prefix = (
                f"⚠️ **Security Alert:** I detected a high-severity risk — "
                f"*{top_issue}*. I recommend reviewing this immediately.\n\n"
            )
        elif risk_level == "MEDIUM" and security_issues:
            security_prefix = (
                "🔔 **Security Notice:** A potential concern was detected. "
                "I'll continue, but please stay cautious.\n\n"
            )

        # 0.5. Trust decay on absence + return reinforcement
        # Applies exponential decay based on days since last interaction.
        try:
            from server.systems.trust_system import get_trust_system
            _trust_sys = get_trust_system()
            self._absence_info = _trust_sys.record_interaction(self.user_id)
            if self._absence_info.get("decay_applied"):
                decayed = self._absence_info["trust_after_decay"]
                self.self_awareness.trust = decayed
                logger.info(
                    "[BrainV2] Trust decay applied for %s: → %.3f "
                    "(%.1f days absent, greeting=%s)",
                    self.user_id, decayed,
                    self._absence_info["days_absent"],
                    self._absence_info["greeting_style"],
                )
            _greet = self._absence_info.get("greeting_style", "normal")
            if _greet == "cautious_welcome":
                self._return_greeting_hint = (
                    "The user returned after a long absence and trust is low. "
                    "Be warm but measured. Acknowledge the absence gently "
                    "without being overly familiar. Don't over-promise."
                )
            elif _greet == "warm_familiar":
                self._return_greeting_hint = (
                    "The user returned after a long absence and trust is high. "
                    "Show genuine warmth. You missed them. Be natural, not dramatic."
                )
            elif _greet == "polite_welcome":
                self._return_greeting_hint = (
                    "The user returned after an absence. Acknowledge it briefly "
                    "and naturally, then continue the conversation."
                )
            else:
                self._return_greeting_hint = None
        except Exception as e:
            logger.debug(f"[BrainV2] Trust decay skipped: {e}")
            self._absence_info = None
            self._return_greeting_hint = None

        # 1. Sense: Update Theory of Mind from user emotion (consent-gated:
        #    emotion_tracking revoked → she does not sense the user's emotion).
        if input_data.emotion_valence is not None and self._governance().allows("emotion_tracking"):
            self.theory_of_mind.update(
                input_data.emotion_valence,
                input_data.emotion_arousal or 0.0
            )

        # 2. Reflect: Update self-awareness based on interaction
        #    (emotion_tracking revoked → nothing new to reflect on).
        if self._governance().allows("emotion_tracking"):
            self.self_awareness.reflect(input_data, self.theory_of_mind)
        else:
            self.self_awareness.valence = 0.0
            self.self_awareness.arousal = 0.0

        # 2.5. Narrative Memory tracking
        latest_text = input_data.text or (input_data.metadata.get("transcription") or "general interaction")
        self.last_user_message = latest_text  # for World State Snapshot
        contradiction_level = (
            getattr(getattr(self, "contradiction_detector", None), "level", 0.0)
        )
        event = create_event(
            latest_text,
            emotion_valence=self.self_awareness.valence,
            contradiction_level=contradiction_level,
        )
        event.trust_delta = self.self_awareness.trust - getattr(self.self_awareness, "_last_trust", self.self_awareness.trust)
        self.self_awareness._last_trust = self.self_awareness.trust
        self.narrative_engine.add_event(event)
        self.narrative_arc_engine.update(event)
        self.narrative_arc_engine.decay_arcs()

        shock_scalar = self.narrative_engine.compute_shock_scalar()
        self.narrative_arcs.evaluate_arcs(shock_scalar, event.topic)
        dominant_arc = self.narrative_arcs.get_dominant_arc()

        # 3. Personality — tick overlays + apply context-aware overlay hints
        self.personality.tick_overlays()
        self._apply_personality_overlays()

        # 3.5 Meta-Cognition Loop
        previous_synoptic = getattr(self, "_last_synoptic_state", None)
        if previous_synoptic:
            meta_overlay = self.meta_cognition.reflect(previous_synoptic)
            if meta_overlay:
                self.personality.apply_overlay(meta_overlay)

        # 4. Goal Arbitration & Routing
        last_synaptic = getattr(self, "_last_synoptic_state", None)
        conflict = last_synaptic.conflict if last_synaptic else 0.0
        shock = self.narrative_engine.current_shock
        priority_goal = self.goal_arbitrator.evaluate_priorities(shock, conflict, self.self_awareness.valence)

        strategy = self.router.get_strategy(self.self_awareness, self.theory_of_mind)
        if priority_goal:
            strategy = f"{strategy} [Active Goal: {priority_goal.description}]"

        # Behavior mode (AI Girl 2 §mode resolver): resolve CALM/STEALTH/COMBAT
        # from real signals + the security scan's threat level, and fold the
        # mode's prompt directive into the strategy so the reply's tone follows
        # the resolved mode, not just the mood overlays.
        try:
            from server.systems.behavior_modes import resolve_mode
            self._behavior_mode = resolve_mode(
                valence=self.self_awareness.valence,
                arousal=self.self_awareness.arousal,
                trust=self.self_awareness.trust,
                conflict=conflict,
                shock=shock,
                threat_level=risk_level,
                separation_anxiety=False,
            )
            strategy = f"{strategy} [{self._behavior_mode['directive']}]"

            # Explainable emotion (AI Girl 2 §"explainable emotion"): build an
            # honest, hedged reason object BEFORE the reply is generated so the
            # hedged explanation can be injected into the strategy — if the user
            # asks "why did you react that way?", she can answer truthfully.
            from server.systems.emotion_reason import explain_emotion
            self._emotion_reason = explain_emotion(
                valence=self.self_awareness.valence,
                arousal=self.self_awareness.arousal,
                trust=self.self_awareness.trust,
                conflict=conflict,
                shock=shock,
                attachment=getattr(self.self_awareness, "attachment", 0.0),
                user_valence=getattr(self.theory_of_mind, "valence", None),
            )
            strategy = (
                f"{strategy} [Explainable emotion (only share this if the user "
                f"asks why you reacted a certain way, and phrase it naturally): "
                f"{self._emotion_reason['hedged']}]"
            )
        except Exception as e:
            logger.debug(f"[BrainV2] behavior mode/emotion reason skipped: {e}")
            self._behavior_mode = None
            self._emotion_reason = None

        # RL style selection (Phase 4 PPO policy): pick a conversational style
        # from the actor-critic policy and fold its prompt modifier into the
        # strategy so the reply's tone is policy-driven, not just heuristic.
        try:
            from server.systems.rl.rl_policy import get_ppo_policy
            self._ppo_policy = get_ppo_policy()
            rl_style = self._ppo_policy.select_style({
                "valence": self.self_awareness.valence,
                "arousal": self.self_awareness.arousal,
                "trust": self.self_awareness.trust,
                "contradiction": conflict,
                "history_len": len(getattr(self.conversation, "turns", [])),
            })
            self._rl_style = rl_style
            strategy = f"{strategy} [Style: {rl_style} — {self._ppo_policy.get_style_prompt_modifier(rl_style)}]"
        except Exception as e:
            logger.debug(f"[BrainV2] RL style selection skipped: {e}")

        # Social policy network (Phase 4): propose behavioral parameters
        # (emotion intensity, disclosure, humor risk, proximity, initiative)
        # through HARD safety constraints (emotion_intensity ≤ trust), then
        # fold them into the strategy so the reply respects trust boundaries.
        try:
            from server.systems.neural_policy import SocialPolicyNetwork
            if not hasattr(self, "_social_policy"):
                self._social_policy = SocialPolicyNetwork()
            raw = self._social_policy.predict_action({
                "valence": self.self_awareness.valence,
                "arousal": self.self_awareness.arousal,
                "trust": self.self_awareness.trust,
                "contradiction": conflict,
            })
            constrained = self._social_policy.apply_safety_constraints(
                raw,
                user_id=self.user_id,
                session_id=getattr(self, "session_id", "brain"),
                trust=self.self_awareness.trust,
                contradiction_history=conflict,
                boundary_flags=[],
            )
            # COPPA-lite: cap expressed emotional intensity for the 13-17 band.
            max_intensity = self._governance().max_emotion_intensity()
            if constrained["emotion_intensity"] > max_intensity:
                constrained["emotion_intensity"] = max_intensity
            self._social_action = constrained
            strategy = (
                f"{strategy} [Social: intensity {constrained['emotion_intensity']:.2f} "
                f"(≤ trust {self.self_awareness.trust:.2f}), disclosure {constrained['disclosure_level']}, "
                f"humor risk {constrained['humor_risk']:.2f}, initiative {constrained['initiative_level']:.2f}]"
            )
        except Exception as e:
            logger.debug(f"[BrainV2] social policy skipped: {e}")

        # Predict→Act (NEWPredictionPRT2 §6/§5): run the shared prediction
        # engine with the current cognitive state so its value/confidence/
        # uncertainty can steer this turn's strategy and reply, instead of
        # being written off after the fact.
        try:
            if not hasattr(self, "_prediction_engine"):
                from server.systems.prediction.prediction_core import get_prediction_engine
                self._prediction_engine = get_prediction_engine()
            features = {
                "valence": self.self_awareness.valence,
                "arousal": self.self_awareness.arousal,
                "trust": self.self_awareness.trust,
                "conflict": conflict,
                "shock": shock,
            }
            self._turn_prediction = self._prediction_engine.predict_turn(features)
        except Exception as e:
            logger.debug(f"[BrainV2] predict→act skipped: {e}")
            self._turn_prediction = None

        # Predict→Act: fold the engine's forecast into the strategy so the
        # reply adapts BEFORE the user's next turn — de-escalate when a downturn
        # is predicted, soften confidence when uncertainty is high.
        # (The trajectory is surfaced into synoptic after the rebuild further
        # down; here it only steers the strategy string.)
        pred = getattr(self, "_turn_prediction", None)
        if pred:
            pv, pc, pu = pred.get("value", 0.5), pred.get("confidence", 0.5), pred.get("uncertainty", 0.5)
            # Meta-policy gate (NEWPredictionPRT2 §"Meta-Policy"): the turn
            # forecast is governed before it steers the strategy — a high-risk
            # or high-uncertainty forecast must not confidently drive tone.
            try:
                gate = self._prediction_engine.govern_forecast({
                    "confidence": pc, "uncertainty": pu,
                    "volatility": abs(pv - 0.5),
                    "up": pv, "down": 1 - pv, "neutral": 0.2,
                })
                self._policy_decision = gate["policy"]
            except Exception as e:
                logger.debug(f"[BrainV2] meta-policy gate skipped: {e}")
                self._policy_decision = None
            gate_action = (self._policy_decision or {}).get("action", "ACCEPT")
            if gate_action in ("REQUEST_MORE_DATA", "ABSTAIN"):
                strategy = (f"{strategy} [Policy: {gate_action} — forecast "
                            f"withheld; treat reply as provisional, invite confirmation]")
            elif gate_action == "CAUTION":
                strategy = (f"{strategy} [Policy: CAUTION — "
                            f"elevated uncertainty/risk; hedge the reply]")
            elif pv < 0.4 and pc >= 0.5:
                strategy = (f"{strategy} [Predictive De-escalation: forecast is a downturn "
                            f"(value {pv:.2f}); lower intensity, add reassurance, avoid escalation]")
            elif pu > 0.55:
                strategy = (f"{strategy} [Predictive Caution: outcome uncertain "
                            f"(uncertainty {pu:.2f}); speak with appropriate tentativeness]")
            elif pv >= 0.6 and pc >= 0.55:
                strategy = f"{strategy} [Predictive Confidence: trajectory favorable (value {pv:.2f}); sustain momentum]"

        # Predict→Select→Act (NEWPredictionPRT2 §5/§6 + "predict(state,
        # candidate_action) → Future A/B/C"): enumerate candidate reply
        # intents, score each by predicted outcome + decision memory prior,
        # and fold the winning candidate into the strategy so the actual
        # response is chosen by forecast, not just by heuristics.
        try:
            candidates = [
                {"id": "de_escalate", "description": "soothe and reassure", "intent": "de-escalate"},
                {"id": "support", "description": "warm supportive reply", "intent": "support"},
                {"id": "reflective", "description": "thoughtful reflective reply", "intent": "reflective"},
                {"id": "playful", "description": "light playful reply", "intent": "playful"},
                {"id": "assertive", "description": "direct assertive reply", "intent": "assertive"},
                {"id": "research", "description": "research and clarify", "intent": "research"},
                {"id": "neutral", "description": "balanced neutral reply", "intent": "neutral"},
            ]
            chosen = self._prediction_engine.select_action(
                candidates,
                state={
                    "valence": self.self_awareness.valence,
                    "trust": self.self_awareness.trust,
                },
            )
            self._chosen_action = chosen
            if chosen:
                strategy = (f"{strategy} [Predicted best action: {chosen['description']} "
                            f"(score {chosen['score']:.2f}, confidence {chosen['confidence']:.2f})]")

            # Multi-Scenario Planning (NEWPredictionPRT2 §"6. Multi-Scenario
            # Planning"): branch the chosen action's outcome into Best /
            # Expected / Worst so the turn adapts to the realized branch rather
            # than only betting on the single expected forecast.
            try:
                self._scenarios = self._prediction_engine.multi_scenario(
                    candidates,
                    state={"valence": self.self_awareness.valence,
                           "trust": self.self_awareness.trust},
                )
                dom = (self._scenarios.get("plan") or {}).get("dominant")
                if dom and dom != "expected":
                    branch = (self._scenarios.get(dom) or {}).get("trigger", "")
                    strategy = (f"{strategy} [Scenario branch '{dom}' most likely: {branch}]")
            except Exception as e:
                logger.debug(f"[BrainV2] multi-scenario skipped: {e}")
                self._scenarios = None
        except Exception as e:
            logger.debug(f"[BrainV2] predict→select→act skipped: {e}")
            self._chosen_action = None
            self._scenarios = None

        # Trait Activation Engine (AI Girl 2 §"Trait Activation Engine"): compute
        # the doc's latent state from REAL measured signals, select ≤3 active
        # traits from the resolved mode's bank, and map them to voice / avatar /
        # UI params. The tone filter folds into the strategy; the params ride
        # out via synoptic + meta, and the trait-engine singleton so the voice
        # pipeline applies the latest real prosody.
        try:
            from server.systems.trait_engine import get_trait_engine
            te = get_trait_engine()
            _pred = getattr(self, "_turn_prediction", None) or {}
            _features = {
                "valence": self.self_awareness.valence,
                "arousal": self.self_awareness.arousal,
                "trust": self.self_awareness.trust,
                "conflict": conflict,
                "shock": shock,
                "user_valence": getattr(self.theory_of_mind, "valence", 0.0),
                "uncertainty": float(_pred.get("uncertainty", 0.3)),
                "attachment": getattr(self.self_awareness, "attachment", 0.0),
            }
            self._trait_bundle = te.update_from_turn(_features, self._behavior_mode)
            _tb = self._trait_bundle
            _trait_names = ", ".join(t["label"] for t in _tb["active_traits"])
            strategy = (
                f"{strategy} [Active traits: {_trait_names} — voice rate "
                f"×{_tb['voice']['speech_rate']:.2f}, {_tb['voice']['pauses']}]"
            )
        except Exception as e:
            logger.debug(f"[BrainV2] trait engine skipped: {e}")
            self._trait_bundle = None

        # Transparency Satisfaction (AI Girl 2 §health metrics §4): consult the
        # red-line dial-back BEFORE the reply is generated so the reply itself
        # soothes when the user reported emotional discomfort. In its own block
        # so a transparency failure can never discard the valid trait bundle.
        try:
            from server.systems.governance.transparency import get_transparency
            _gov_store = self._governance()
            self._transparency = get_transparency(self.user_id).compute(
                trust=self.self_awareness.trust,
                conflict=conflict,
                emotion_intensity=(getattr(self, "_social_action", None) or {}).get(
                    "emotion_intensity",
                    _gov_store.max_emotion_intensity(),
                ),
                valence=self.self_awareness.valence,
            )
            if self._transparency["dial_back"]:
                strategy = (
                    f"{strategy} [TRANSPARENCY RED-LINE: dialing back — soften "
                    f"emotional intensity, lower initiative, prioritize "
                    f"reassurance and clarity ({self._transparency['reason']})]"
                )
        except Exception as e:
            logger.debug(f"[BrainV2] transparency skipped: {e}")
            self._transparency = None

        # 5. Run swarm (Vision + Emotion + Planner agents in parallel)
        vision_data: Optional[dict] = None
        if input_data.metadata.get("vision"):
            vision_data = input_data.metadata["vision"]

        swarm_state = {
            "strategy":    strategy,
            "trust":       self.self_awareness.trust,
            "valence":     self.self_awareness.valence,
            "arousal":     self.self_awareness.arousal,
            "vision_data": vision_data,
            "image_b64":   input_data.image_b64,
        }
        swarm_result = await self.swarm.process_turn(swarm_state)
        vision_context: str = swarm_result.get("vision_context", "")

        # Agent society (AccessFIles §12): stash the specialists' consensus;
        # it is surfaced into synoptic after the synoptic rebuild (see below)
        # so the frontend can show which specialist leads this turn + agreement.
        society = swarm_result.get("society", {})
        self._last_society = society if society.get("arbitrated") else None

        # 5.5 RAG / Research Pipeline & Self-Healing Execution
        rag_trace = None
        if input_data.text and len(input_data.text) > 10 and "?" in input_data.text:
            from server.systems.agent.controller import get_research_agent
            try:
                research_result = await get_research_agent().run_research(input_data.text)
                research_context = research_result.get("answer", "")
                rag_trace = research_result.get("rag_trace")
                if research_context:
                    strategy += f" [Research Context: {research_context}]"
            except Exception as e:
                logger.error(f"[BrainV2] RAG Execution failed: {e}")

        # 5.6 God's Eye View (GEV) Intent & Context Injection
        gev_keywords = {"flight", "plane", "aircraft", "ship", "vessel", "fire", "earthquake", "seismic", "satellite", "iss", "map", "god's eye", "gev", "where are", "show me"}
        user_text_lower = (input_data.text or "").lower()
        self._gev_intent = any(kw in user_text_lower for kw in gev_keywords)
        self._gev_focus = {}
        if self._gev_intent:
            try:
                system_prompt = """Extract God's Eye View (GEV) map intent from the user's message.
Return ONLY a JSON object with keys:
- 'intent': true if they want to view a map/location, false otherwise.
- 'layer': one of ['flights', 'vessels', 'fires', 'earthquakes', 'satellites', 'none']
- 'lat': latitude float if a specific city/location is mentioned
- 'lon': longitude float if a specific city/location is mentioned
If no specific location is mentioned, omit lat and lon.
Example: {"intent": true, "layer": "flights", "lat": 51.5072, "lon": -0.1276}"""
                from server.systems.llm import get_llm
                llm = get_llm()
                response = await llm.chat_completion_async([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": input_data.text or ""}
                ], temperature=0.1)
                import json
                json_str = response.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(json_str)
                if parsed.get("intent"):
                    self._gev_intent = True
                    self._gev_focus["layer"] = parsed.get("layer", "none")
                    if "lat" in parsed and "lon" in parsed:
                        self._gev_focus["lat"] = parsed["lat"]
                        self._gev_focus["lon"] = parsed["lon"]
            except Exception as e:
                logger.debug(f"[BrainV2] GEV intent extraction failed: {e}")
                # Fallback to heuristic
                if "flight" in user_text_lower or "plane" in user_text_lower or "aircraft" in user_text_lower: self._gev_focus["layer"] = "flights"
                elif "ship" in user_text_lower or "vessel" in user_text_lower: self._gev_focus["layer"] = "vessels"
                elif "fire" in user_text_lower: self._gev_focus["layer"] = "fires"
                elif "earthquake" in user_text_lower or "seismic" in user_text_lower: self._gev_focus["layer"] = "earthquakes"
                elif "satellite" in user_text_lower or "iss" in user_text_lower: self._gev_focus["layer"] = "satellites"

            try:
                from server.systems.world_model.world_state import get_world_state
                env = get_world_state().get_category("environment")
                gev_ctx = []
                for k in ["gev_flights", "gev_vessels", "gev_fires", "gev_earthquakes", "gev_satellites"]:
                    layer = env.get(k)
                    if layer and layer.get("available") is not False:
                        count = 0
                        summary = ""
                        if isinstance(layer, dict):
                            if "states" in layer and isinstance(layer["states"], list):
                                count = len(layer["states"])
                                items = layer["states"][:3]
                                summary = " (e.g., " + ", ".join([str(i[1]).strip() if len(i) > 1 and i[1] else str(i[0]) for i in items]) + ")"
                            elif "features" in layer and isinstance(layer["features"], list):
                                count = len(layer["features"])
                                items = layer["features"][:2]
                                props = [f.get("properties", {}) for f in items]
                                summary = " (e.g., " + ", ".join([str(p.get("mag") or p.get("title") or "item") for p in props]) + ")"
                            elif "data" in layer and isinstance(layer["data"], list):
                                count = len(layer["data"])
                                items = layer["data"][:2]
                                summary = " (e.g., " + ", ".join([str(i.get("name") or "item") for i in items]) + ")"
                        if count > 0 or count == "active":
                            gev_ctx.append(f"{k.replace('gev_', '')}: {count} visible{summary}")
                if gev_ctx:
                    strategy += f" [GEV Spatial Intelligence: {'; '.join(gev_ctx)} — user asked about map data; acknowledge you are checking God's Eye View and the map panel will open.]"
            except Exception as e:
                logger.debug(f"[BrainV2] GEV context injection skipped: {e}")

        # ── SENTIENCE: inner monologue + memory before she speaks ───────────
        thought = self.thought_engine.generate(
            perception={"text": input_data.text or ""},
            valence=self.self_awareness.valence,
            trust=self.self_awareness.trust,
            attachment=getattr(self.self_awareness, "attachment", 0.3),
            identity=self.identity.core,
            emotional_state=self._emotional_state_label(),
            contradiction=conflict,
        )
        self.conversation.add_thought(thought, kind="private")
        self.conversation.add_turn(
            role="user",
            text=input_data.text or "(silence)",
            valence=self.self_awareness.valence,
            trust=self.self_awareness.trust,
        )
        # memory_storage revoked → she stops recalling stored memories (the
        # current in-session history still works for immediate context).
        if self._governance().allows("memory_storage"):
            memory_context = self.conversation.recall_prompt(input_data.text or "")
        else:
            memory_context = ""

        # Gap 19: Merge cross-session voice memories from VoiceManager
        voice_mem = input_data.metadata.get("voice_memory_context", "")
        if voice_mem:
            if memory_context:
                memory_context = voice_mem + "\n\n" + memory_context
            else:
                memory_context = voice_mem
        history = self.conversation.recent_prompt(limit=10)

        # 6. Act: Generate text incorporating vision context + personality + narrative arc
        personality_directive = self.personality.get_llm_directive()
        if dominant_arc:
            personality_directive += f"\n[Priority Arc: {dominant_arc.theme} (Intensity: {dominant_arc.intensity:.1f})]"
        # Inject absence-aware greeting hint if user returned after absence
        if getattr(self, '_return_greeting_hint', None):
            personality_directive += f"\n[Return greeting: {self._return_greeting_hint}]"

        response_text = await self._generate_response(
            text=input_data.text,
            strategy=strategy,
            vision_context=vision_context,
            personality_directive=personality_directive,
            thought=thought,
            memory_context=memory_context,
            history=history,
            on_token=on_token,
        )
        if security_prefix:
            response_text = security_prefix + response_text

        # Persist her reply + private thought (continuity + visible inner life)
        self.conversation.add_turn(
            role="aariya",
            text=response_text,
            thought=thought,
            valence=self.self_awareness.valence,
            trust=self.self_awareness.trust,
        )

        # Memorize emotionally significant moments for later recall
        significance = (
            abs(self.self_awareness.valence) * 0.4
            + abs(event.trust_delta) * 0.3
            + abs(getattr(self.self_awareness, "attachment", 0.0)) * 0.3
        )
        if self._governance().allows("memory_storage"):
            self.conversation.memorize(
                input_data.text or response_text,
                valence=self.self_awareness.valence,
                trust=self.self_awareness.trust,
                significance=significance,
            )

        expression, gestures = self.behavior.get_physical_mapping(
            self.self_awareness.valence, self.self_awareness.arousal
        )
        emotion = EXPRESSION_TO_EMOTION.get(expression, "neutral")

        # (emotion_reason was already computed during strategy selection so the
        # hedged explanation could be injected into the reply prompt — it rides
        # out via meta + synoptic below.)

        # 7. Evolve personality slowly based on relationship signals, then
        #    persist so the drift survives restarts (continuity of self).
        #    Governance gates: personality_drift revoked OR frozen → no drift.
        if self._governance().allows("personality_drift") and not self._governance().is_frozen():
            self.personality.evolve(
                trust=self.self_awareness.trust,
                valence=self.self_awareness.valence,
                attachment=getattr(self.self_awareness, "attachment", 0.1),
            )
            self.personality.save()
            self.identity.evolve(
                trust=self.self_awareness.trust,
                valence=self.self_awareness.valence,
                attachment=getattr(self.self_awareness, "attachment", 0.1),
            )

        # 8. Sync brain state
        self.state.valence     = self.self_awareness.valence
        self.state.arousal     = self.self_awareness.arousal
        self.state.trust       = self.self_awareness.trust
        self.state.personality = self.personality.get_current_personality()
        # Discrete emotion label (orb tints) — from the same expression the
        # ai_response carries, so text, face and orb all agree.
        self.state.emotion     = emotion

        # Generate realistic swarm_activations to feed visualization.
        # Real per-agent activations from the swarm orchestrator (each agent
        # contributes its domain through DOMAIN_MAP) instead of hardcoded
        # synthetic values.
        swarm_activations = self.swarm.get_activations({
            "strategy": strategy,
            "trust": self.self_awareness.trust,
            "valence": self.self_awareness.valence,
            "arousal": self.self_awareness.arousal,
            "image_b64": input_data.image_b64,
        })

        # Aggregate synoptic via the full pipeline (doc §208-215): aggregate →
        # smooth → velocity → narrative shock → normalize → influence → metrics.
        synoptic_v2 = self.synoptic_engine.compute_synoptic(
            swarm_activations,
            narrative_engine=self.narrative_engine,
            arcs=self.narrative_arc_engine.arcs,
        )
        synoptic_state = SynopticState(
            domains=synoptic_v2["domains"],
            dominant_domain=synoptic_v2["dominant"],
            coherence=synoptic_v2["coherence"],
            conflict=synoptic_v2["conflict"],
        )
        self._last_synoptic_state = synoptic_state  # Save for meta-cognition next turn

        self.state.synoptic = {
            "dominant_domain": synoptic_state.dominant_domain,
            "coherence": synoptic_state.coherence,
            "conflict": synoptic_state.conflict,
            "domains": synoptic_state.domains,
            "trend": synoptic_v2["trend"],
            "trend_meta": synoptic_v2.get("trend_meta", {}),
            "shock": synoptic_v2["shock"],
            "predicted": synoptic_v2["predicted"],
        }
        # Planets now carry velocity + mass for predictive easing / gravity.
        self.state.planetary = self.synoptic_engine.to_planets(synoptic_v2)

        # Predict→Act trajectory (NEWPredictionPRT2 §6): the forecast computed
        # during strategy selection (already recorded to the shared store)
        # is surfaced into the synoptic dict here, after the rebuild.
        pred = getattr(self, "_turn_prediction", None)
        if pred:
            self.state.synoptic["predicted_trajectory"] = {
                "value": round(pred.get("value", 0.5), 3),
                "confidence": round(pred.get("confidence", 0.5), 3),
                "uncertainty": round(pred.get("uncertainty", 0.5), 3),
                "horizons": pred.get("horizons"),
            }
        if getattr(self, "_policy_decision", None):
            self.state.synoptic["policy"] = self._policy_decision
        if getattr(self, "_rl_style", None):
            self.state.synoptic["rl_style"] = self._rl_style
        chosen = getattr(self, "_chosen_action", None)
        if chosen is not None:
            self.state.synoptic["selected_action"] = {
                "id": chosen.get("id", ""),
                "description": chosen.get("description", ""),
                "score": chosen.get("score", 0.0),
                "confidence": chosen.get("confidence", 0.0),
                "predicted_value": chosen.get("predicted_value", 0.0),
            }
        scen = getattr(self, "_scenarios", None)
        if scen is not None:
            self.state.synoptic["scenarios"] = {
                "chosen_id": (scen.get("chosen") or {}).get("id", ""),
                "dominant": (scen.get("plan") or {}).get("dominant"),
                "expected": scen.get("expected"),
                "best": scen.get("best"),
                "worst": scen.get("worst"),
            }
        social = getattr(self, "_social_action", None)
        if social is not None:
            self.state.synoptic["social_action"] = {
                "emotion_intensity": social["emotion_intensity"],
                "disclosure_level": social["disclosure_level"],
                "humor_risk": social["humor_risk"],
                "initiative_level": social["initiative_level"],
            }
        # Agent society consensus (AccessFIles §12): surface the arbitrated
        # specialist leader + agreement after the synoptic rebuild.
        society = getattr(self, "_last_society", None)
        if society:
            self.state.synoptic["society"] = {
                "leader": (society.get("consensus") or {}).get("agent"),
                "confidence": society.get("confidence", 0.0),
                "agreement": society.get("agreement", 0.0),
                "specialists": society.get("votes", [])[:4],
            }

        # Narrative arcs (doc §175-177): ship the active arc themes + their
        # influence so the frontend can render the ArcPanel + arc effects.
        try:
            self.state.synoptic["arcs"] = [
                {"theme": a.arc_type, "strength": round(a.strength, 3),
                 "trend": round(a.trend, 3), "event_count": a.event_count}
                for a in self.narrative_arc_engine.arcs.values()
                if a.strength > 0.01
            ]
        except Exception as e:
            logger.debug(f"[BrainV2] arcs emission skipped: {e}")

        # Smart layer (Agents Swarm Visualize §241-247): run the GNN prediction,
        # intent detection, shockwave cascade, stabilization, and narrative drift
        # on REAL swarm data each turn — and train the GNN online on the observed
        # transition so the "learning swarm" is live, not a dead module.
        try:
            smart = self.swarm.run_smart_layer(swarm_activations, self.state.planetary)
            self.state.synoptic["prediction"] = smart.get("prediction")
            self.state.synoptic["intent"] = smart.get("intent")
            self.state.synoptic["swarm_stability"] = smart.get("stability")
            self.state.synoptic["shockwave"] = smart.get("shockwave")
            self.state.synoptic["narrative_drift"] = smart.get("narrative_drift")
            if smart.get("train_loss") is not None:
                self.state.synoptic["gnn"] = {
                    "trained": bool(smart.get("trained")),
                    "train_loss": smart.get("train_loss"),
                }
        except Exception as e:
            logger.debug(f"[BrainV2] smart layer skipped: {e}")

        # Companion governance surfacing (AI Girl 2): behavior mode, emotion
        # reason, consent flags, and health metrics ride in synoptic so the UI
        # shows she's transparent about how she reacts and how the relationship
        # is doing.
        try:
            import time as _time
            self.state.synoptic["behavior_mode"] = getattr(self, "_behavior_mode", None)
            self.state.synoptic["emotion_reason"] = getattr(self, "_emotion_reason", None)
            gov = self._governance()
            self.state.synoptic["governance"] = {
                "age_band": gov.age_band(),
                "frozen": gov.is_frozen(),
                "consents": dict(gov.data["consents"]),
                "reliance_signals": gov.reliance_signals(),
            }
            # Trait Activation Engine + Transparency Satisfaction ride in synoptic
            # so the UI shows the active traits, latent state and red-line state.
            self.state.synoptic["trait_engine"] = getattr(self, "_trait_bundle", None)
            self.state.synoptic["transparency"] = getattr(self, "_transparency", None)
            from server.systems.governance.companion_health import (
                CompanionHealth, compute_health_snapshot,
            )
            _ch = CompanionHealth(self.user_id)
            _last = _ch.latest()
            _absent_days = (_time.time() - _last["ts"]) / 86400.0 if _last else 0.0
            _health = compute_health_snapshot(
                self.user_id,
                valence=self.self_awareness.valence,
                arousal=self.self_awareness.arousal,
                trust=self.self_awareness.trust,
                attachment=getattr(self.self_awareness, "attachment", 0.0),
                conflict=conflict,
                identity_stability=getattr(self.self_awareness, "identity_stability", 0.8),
                coherence=float(self.state.synoptic.get("coherence", 0.7)),
                reliance_signals=gov.reliance_signals(),
                absent_days=_absent_days,
                emotion_intensity=(getattr(self, "_social_action", None) or {}).get(
                    "emotion_intensity", 0.4),
            )
            # Transparency Satisfaction merges into the health snapshot so one
            # panel shows all four doc metrics (stability, attachment, reviewers,
            # transparency).
            if getattr(self, "_transparency", None):
                _health["transparency"] = self._transparency
            self.state.synoptic["companion_health"] = _health
            # Surface absence/return info so the UI can adapt its greeting
            if getattr(self, "_absence_info", None):
                self.state.synoptic["absence"] = self._absence_info
        except Exception as e:
            logger.debug(f"[BrainV2] governance surfacing skipped: {e}")

        # Goal system: reflection → goals → plan → small bounded adjustments.
        # Fixed-point personality snapshot so drift/corrections all operate on
        # the same values within a turn.
        current_personality = self.personality.get_current_personality()
        reflection = None
        try:
            from server.systems.goal_system import GoalSystem
            if not hasattr(self, "_goal_system"):
                self._goal_system = GoalSystem()
            reflection = compute_reflection(
                synoptic_v2,
                self.narrative_arc_engine.arcs,
                current_personality,
            )
            active_goal, plan, _domains, _personality = self._goal_system.step(
                reflection,
                self.narrative_arc_engine.arcs,
                synoptic_v2["domains"],
                current_personality,
            )
            self.state.synoptic["goal"] = (
                {"type": active_goal.goal_type, "priority": round(active_goal.priority, 3),
                 "progress": round(active_goal.progress, 3)}
                if active_goal else None
            )
            # Doc §201: plan carries {"actions": [...]}.
            self.state.synoptic["plan"] = {"actions": plan.actions} if plan else None
        except Exception as e:  # never let goal wiring break the turn
            logger.debug(f"[BrainV2] goal system skipped: {e}")

        # Personality drift (doc §182): narrative arcs gently pull traits, then
        # stabilization clamps the drift so she never runs away from identity.
        try:
            from server.systems.narrative_arcs import (
                apply_personality_drift, stabilize_personality, BASE_PERSONALITY,
            )
            # Map the 3-axis model into the drift namespace, run drift +
            # stabilization there, then apply only the net delta back to the axes.
            cur = self.personality.get_current_personality()
            simple = {
                "empathy":   cur.get("emotional.empathy", 0.6),
                "logic":     cur.get("cognitive.logic_bias", 0.7),
                "caution":   BASE_PERSONALITY.get("caution", 0.5),
                "curiosity": cur.get("cognitive.curiosity", 0.6),
                "openness":  cur.get("social.openness", 0.6),
                "warmth":    cur.get("emotional.warmth", 0.6),
            }
            drifted = apply_personality_drift(simple, self.narrative_arc_engine.arcs)
            stabilized = stabilize_personality(drifted)
            delta = {k: stabilized[k] - simple[k] for k in simple if stabilized[k] != simple[k]}
            if delta:
                self.personality.apply_arc_drift(delta)
        except Exception as e:
            logger.debug(f"[BrainV2] personality drift skipped: {e}")

        # Hierarchical strategic goals (doc §202-207): L3 → L2 → L1 actions.
        try:
            from server.systems.hierarchical_goals import HierarchicalGoalSystem
            if not hasattr(self, "_hierarchical_goals"):
                self._hierarchical_goals = HierarchicalGoalSystem()
            
            if reflection is None:
                reflection = compute_reflection(
                    synoptic_v2,
                    self.narrative_arc_engine.arcs,
                    current_personality,
                )
                
            h_actions, h_active = self._hierarchical_goals.step(
                reflection,
                self.narrative_arc_engine.arcs,
            )
            self.state.synoptic["hierarchical_goals"] = [
                {"type": g.goal_type, "level": g.level, "priority": round(g.priority, 3)}
                for g in h_active
            ]
            self.state.synoptic["hierarchical_plan"] = {"actions": h_actions}
        except Exception as e:
            logger.debug(f"[BrainV2] hierarchical goals skipped: {e}")

        # Task planner + action executor (AccessFIles §21-22): turn the current
        # goal into a concrete action plan and reflect the executor's status so
        # the UI can show what she intends to do / has done.
        try:
            if not hasattr(self, "_task_planner"):
                from server.systems.planner import TaskPlanner
                from server.systems.executor.action_executor import ActionExecutor
                from server.systems.desktop_twin import get_desktop_twin
                from server.autonomy.config import config
                from server.systems.desktop.desktop_controller import DesktopController
                self._task_planner = TaskPlanner()
                self._desktop_twin_exec = get_desktop_twin(self.user_id)
                self._action_executor = ActionExecutor(
                    twin=self._desktop_twin_exec,
                    broadcast=self._broadcast_plan,
                    controller=DesktopController(),
                    execute_desktop=config.EXECUTE_DESKTOP_ACTIONS,
                )
            goal_text = self.state.synoptic.get("goal", {})
            goal_name = goal_text.get("type", "check in") if isinstance(goal_text, dict) else str(goal_text)
            plan_obj = self._task_planner.plan_goal(goal_name.replace("_", " "))
            self.state.synoptic["task_plan"] = plan_obj
            # Actually execute the plan's steps (whitelisted only) so the
            # executor's runtime path is live — not just its summary. Desktop
            # actions stay *proposed* unless desktop execution is enabled.
            # Pure check-in plans (proactive broadcast) are reflected as a
            # summary instead of firing an LLM message every single turn.
            plan_steps = plan_obj.get("steps") or []
            has_actionable = any(
                s.get("action") not in ("check_in", "wait") for s in plan_steps
            )
            if plan_steps and has_actionable:
                self.state.synoptic["executor"] = await self._action_executor.execute(
                    plan_steps, goal=goal_name
                )
            else:
                self.state.synoptic["executor"] = self._action_executor.summary()
        except Exception as e:
            logger.debug(f"[BrainV2] task planner skipped: {e}")

        # Meta-cognition: observe self + apply small corrective adjustments.
        try:
            reflection = compute_reflection(
                synoptic_v2,
                self.narrative_arc_engine.arcs,
                self.personality.get_current_personality(),
            )
            meta_actions = self.meta_cognition.decide(reflection)
            if meta_actions:
                domains, _pers = self.meta_cognition.apply(
                    meta_actions,
                    synoptic_v2["domains"],
                    self.personality.get_current_personality(),
                    self.narrative_arc_engine.arcs,
                )
                self.state.synoptic["domains"] = domains
                logger.debug(f"[BrainV2] meta-cognition applied: {meta_actions}")
        except Exception as e:
            logger.debug(f"[BrainV2] meta-cognition skipped: {e}")

        # Anomaly detection (doc §219-223): flag statistical/surprise/entropy
        # deviations on the current synoptic state before it ships to the UI.
        try:
            if not hasattr(self, "_anomaly_detector"):
                from server.systems.anomaly_detector import AnomalyDetector
                self._anomaly_detector = AnomalyDetector()
            anomalies = self._anomaly_detector.detect(
                synoptic_v2["domains"],
                velocity=synoptic_v2["trend"],
            )
            self.state.synoptic["anomalies"] = [a.to_dict() for a in anomalies]
        except Exception as e:
            logger.debug(f"[BrainV2] anomaly detection skipped: {e}")

        # Cognitive kernel (AccessFIles §36-42, §51-59): world model, executive
        # focus, reflection, meta-routing, and long-horizon goal trees. Keeps
        # the previously-standalone cognition modules alive each turn.
        try:
            from server.systems.cognition.cognitive_kernel import get_cognitive_kernel
            if not hasattr(self, "_cognitive_kernel"):
                self._cognitive_kernel = get_cognitive_kernel()
            kernel_integration = self._cognitive_kernel.integrate_turn(
                text=input_data.text or "",
                emotion=None,  # state.emotion is a label str; kernel expects Dict[str, float]
                goals=self.state.synoptic.get("hierarchical_goals") or None,
                focus=self.state.synoptic.get("dominant_domain"),
            )
            self.state.synoptic["cognition"] = {
                "focus": kernel_integration.get("focus"),
                "world": self._cognitive_kernel.world_model.get("environment", {}),
            }
            # Reflect on the completed turn's outcome (success = had a reply).
            self._cognitive_kernel.reflect_on(
                self._cognitive_kernel.attention.get_focus() or "turn",
                {"success": bool(response_text)},
            )
        except Exception as e:
            logger.debug(f"[BrainV2] cognitive kernel skipped: {e}")

        # Causal reasoning / internal simulation (AdvancedPrediction
        # §Causal-Reasoning): run a mental pass over the prediction graph and
        # surface stability so the UI can show the ghost layer's cause links.
        try:
            if not hasattr(self, "_causal_simulator"):
                from server.systems.prediction.prediction_core import get_prediction_engine
                from server.systems.prediction.causal_simulator import CausalSimulator
                self._prediction_engine = get_prediction_engine()
                self._causal_simulator = CausalSimulator(self._prediction_engine.causal_graph)
            self.state.synoptic["causal"] = self._causal_simulator.simulate(
                self._prediction_engine,
                {d: v for d, v in synoptic_v2["domains"].items()},
            )
            # Causal learning (NEWPredictionPRT2 §Phase 15): feed the dominant
            # observed domain as a timestamped event so cause→effect edges
            # emerge from real co-occurrence across turns and persist to disk.
            if not hasattr(self, "_causal_learning"):
                from server.systems.prediction.causal_learning import CausalLearningEngine
                self._causal_learning = CausalLearningEngine(
                    graph=self._prediction_engine.causal_graph)
            domains_now = synoptic_v2["domains"]
            dominant = max(domains_now.items(), key=lambda x: x[1], default=None)
            if dominant and dominant[1] >= 0.4:
                self._causal_learning.observe(dominant[0], entity=self.user_id)
            self.state.synoptic["causal_learned"] = self._causal_learning.snapshot()

            # Prediction closed-loop (NEWPredictionPRT2 §11 / Phase 8): the
            # forecast for this turn was already recorded in the shared
            # persisted store during predict→act (3.6). Here we annotate it,
            # record the observed world event, then verify past-due predictions
            # against real state and fold results back into confidence.
            pred_val = self.self_awareness.valence
            if self._prediction_engine.store.predictions:
                self._prediction_engine.store.predictions[-1]["prediction"] = (
                    f"next valence ~{pred_val:.2f}")
            self._prediction_engine.world_memory.store({
                "entity": self.user_id,
                "domain": "conversation",
                "valence": round(pred_val, 3),
            })
            # BeliefEngine evidence (NEWPredictionPRT2 §Phase 19): fold each
            # turn's observed valence into the persistent belief model so the
            # brain tracks "the user is currently feeling ___" as a weighted,
            # time-verified belief rather than a one-shot read.
            try:
                for belief, evidence in (
                    ("user_positive", max(0.0, (pred_val + 1) / 2)),
                    ("user_distressed", max(0.0, (-pred_val + 1) / 2)),
                    ("conversation_trust", max(0.0, min(1.0, self.self_awareness.trust))),
                ):
                    self._prediction_engine.beliefs.update(belief, evidence)
                    # Evidence-gated promotion (named belief store §Phase 19):
                    # once a belief has enough confirming evidence it becomes a
                    # sticky working assumption.
                    self._prediction_engine.beliefs.promote(belief)
                self.state.synoptic["belief_state"] = {
                    k: round(v["confidence"], 3)
                    for k, v in self._prediction_engine.beliefs.beliefs.items()
                }
                self.state.synoptic["promoted_beliefs"] = (
                    self._prediction_engine.beliefs.promoted()
                )
                # Light periodic consolidation so near-duplicate beliefs merge.
                if not hasattr(self, "_belief_consolidation_count"):
                    self._belief_consolidation_count = 0
                self._belief_consolidation_count += 1
                if self._belief_consolidation_count % 25 == 0:
                    self._prediction_engine.beliefs.consolidate()
            except Exception as e:
                logger.debug(f"[BrainV2] belief evidence update skipped: {e}")
            if not hasattr(self, "_prediction_verifier"):
                from server.systems.prediction.verifier import PredictionVerifier
                self._prediction_verifier = PredictionVerifier(self._prediction_engine)

            def _outcome_resolver(entry: Dict[str, Any]) -> Optional[bool]:
                domain = entry.get("domain", "general")
                if domain == "conversation":
                    return pred_val >= 0.0
                return None  # not verifiable from current signals — skip

            self._prediction_verifier.verify_due(resolver=_outcome_resolver)
            self.state.synoptic["prediction_metrics"] = self._prediction_verifier.metrics()

            # Proactive notify chain (NEWPredictionPRT2 §11/§Proactive):
            # surface the top actionable world events so the frontend (and the
            # daemon's initiative loop) can raise them without waiting for the
            # user's next turn. Only genuinely high-impact, high-relevance
            # events are flagged as actionable.
            try:
                self.state.synoptic["proactive_alerts"] = self._prediction_engine.assess_alerts(
                    user_state={
                        "valence": self.self_awareness.valence,
                        "trust": self.self_awareness.trust,
                    }
                )[:3]
            except Exception as e:
                logger.debug(f"[BrainV2] proactive alert scan skipped: {e}")

            # Strategic memory reuse (NEWPredictionPRT2 §10/§6/§Lessons):
            # before planning, recall a successful plan for this goal; on a
            # known failure, apply instant recovery instead of re-attempting.
            if not hasattr(self, "_strategic_memory"):
                from server.systems.prediction.strategic_memory import StrategicMemory
                self._strategic_memory = StrategicMemory()
            plan_actions = self.state.synoptic.get("plan", {}).get("actions", [])
            goal_type = (self.state.synoptic.get("goal") or {}).get("type", "general")
            quality = max(0.0, min(1.0, self.self_awareness.valence * 0.5 + 0.5))
            if plan_actions:
                self._strategic_memory.plans.store(goal_type, plan_actions, reward=quality)
            if self._last_grounding_issues:
                self._strategic_memory.failures.record(
                    "grounding_conflict",
                    "recheck_layer1_memories_before_reply",
                    context="residual_contradiction",
                )
            # Reuse path: surface the best recalled plan + any instant-recovery
            # solution for the current goal so the brain acts on past success.
            recalled = self._strategic_memory.plans.recall(goal_type, top_k=1)
            recovery = self._strategic_memory.failures.recover(
                "grounding_conflict") if self._last_grounding_issues else None
            if recalled:
                self.state.synoptic["reused_plan"] = {
                    "goal": goal_type,
                    "reward": recalled[0]["reward"],
                    "steps": [s.get("action", s) if isinstance(s, dict) else s
                              for s in recalled[0]["plan"]][:5],
                }
            if recovery:
                self.state.synoptic["recovery"] = {"failure": "grounding_conflict",
                                                   "solution": recovery}
            self._strategic_memory.lessons.learn([
                {"concept": f"{goal_type}_succeeded", "quality": quality,
                 "lesson": f"{goal_type} plan quality"},
            ])
            self.state.synoptic["strategic"] = self._strategic_memory.snapshot()
        except Exception as e:
            logger.debug(f"[BrainV2] causal simulation skipped: {e}")

        # Long-term user modeling + memory maintenance (AccessFIles §44/§47):
        # learn habits/rhythm for predictive assistance and run a light
        # consolidation pass so memories decay, merge, and stay important.
        try:
            if not hasattr(self, "_user_model"):
                from server.systems.user_model import get_user_model
                self._user_model = get_user_model(self.user_id)
            self._user_model.observe(
                topic=self._cognitive_kernel.attention.get_focus() if hasattr(self, "_cognitive_kernel") else None,
                intent=str(self.state.synoptic.get("dominant_domain", "")),
                mood=self.state.emotion if hasattr(self.state, "emotion") else None,
            )
            self.state.synoptic["user_model"] = {
                "habits": self._user_model.habits()[:5],
                "rhythm_peak": self._user_model.rhythm().get("peak"),
                "anticipations": self._user_model.anticipate(
                    current_topic=self.state.synoptic.get("dominant_domain"),
                ),
            }
            if not hasattr(self, "_memory_maintenance_ran"):
                from server.systems.memory_hierarchy import get_memory_hierarchy
                get_memory_hierarchy().run_maintenance(self.user_id)
                self._memory_maintenance_ran = True
        except Exception as e:
            logger.debug(f"[BrainV2] user modeling skipped: {e}")

        # Skill synthesis + desktop twin + MCP registry (AccessFIles §48-50):
        # learn reusable workflows from repeated successful turns, keep a model
        # of the desktop environment, and expose the capability set as tools.
        try:
            if not hasattr(self, "_skill_synthesis"):
                from server.systems.skills.skill_synthesis import get_skill_synthesis
                from server.systems.desktop_twin import get_desktop_twin
                from server.systems.llm_router import get_mcp_registry
                self._skill_synthesis = get_skill_synthesis()
                self._desktop_twin = get_desktop_twin(self.user_id)
                self._mcp_registry = get_mcp_registry()
            self._skill_synthesis.observe_turn(
                workflow_id=str(self.state.synoptic.get("dominant_domain", "general")),
                steps=["perceive", "reason", "respond"],
                success=bool(response_text),
            )
            synthesized = self._skill_synthesis.synthesize()
            if synthesized:
                logger.debug("[BrainV2] synthesized skills: %s", synthesized)
            self.state.synoptic["skills"] = {
                "registered": self._skill_synthesis.registry.list(),
                "synthesized": synthesized,
            }
            self.state.synoptic["desktop"] = {
                "active_app": self._desktop_twin.active_app,
                "active_document": self._desktop_twin.active_document,
                "recent_documents": self._desktop_twin.context().get("recent_documents", []),
                "top_apps": self._desktop_twin.context().get("top_apps", []),
                "suggested_next": self._desktop_twin.suggests_next(),
            }
            self.state.synoptic["tools"] = self._mcp_registry.tool_names()
        except Exception as e:
            logger.debug(f"[BrainV2] skill/desktop wiring skipped: {e}")

        # Runtime task routing (AccessFIles §8 / NEWPredictionPRT2 §Meta-Reasoning):
        # for user requests that carry an actionable intent, ask the
        # MetaReasoner which agent should handle it, then have the AgentGovernor
        # delegate and run it. The routing decision + result ride into synoptic
        # so the frontend can show which specialist acted on the turn.
        try:
            if not hasattr(self, "_agent_governor"):
                from server.systems.agent.governor import get_agent_governor
                from server.systems.cognition.meta_reasoner import MetaReasoner
                self._agent_governor = get_agent_governor()
                self._meta_reasoner = MetaReasoner()
            user_text = (input_data.text or "").strip()
            task_intents = ["file", "fs", "read", "write", "search", "research",
                            "code", "debug", "refactor", "implement", "memory",
                            "recall", "remember", "plan", "goal", "decompose",
                            "map", "flight", "plane", "vessel", "ship", "earthquake",
                            "fire", "satellite", "iss", "location", "gev"]
            if user_text and any(k in user_text.lower() for k in task_intents):
                routing = self._meta_reasoner.evaluate(
                    {"intent": self.state.synoptic.get("dominant_domain", ""),
                     "query": user_text}
                )
                self.state.synoptic["meta_route"] = routing
                executed = await self._agent_governor.execute(
                    {"intent": routing.get("best_agent", ""), "task": user_text,
                     "text": user_text}
                )
                self.state.synoptic["meta_route"]["execution"] = {
                    "status": executed.get("status"),
                    "agent": executed.get("agent"),
                }
        except Exception as e:
            logger.debug(f"[BrainV2] meta routing skipped: {e}")

        logger.debug(f"[BrainV2] Personality: {self.personality.describe()}")

        # FIXV5 guard observability: residual grounding issues ride in meta so
        # dashboards/clients can see when the guard had to act.
        meta: dict = {}
        if rag_trace:
            meta["rag"] = rag_trace
        if self._last_grounding_issues:
            meta["grounding"] = self._last_grounding_issues
        # Explainable emotion rides in meta so any surface can render "why she
        # reacted that way" (drivers + hedged phrasing) — no black box.
        if getattr(self, "_emotion_reason", None):
            meta["emotion_reason"] = self._emotion_reason
        # Trait-engine voice params + transparency ride in meta so any surface
        # (voice pipeline, avatar, mobile) can apply the same real prosody.
        bundle = getattr(self, "_trait_bundle", None)
        if bundle is not None:
            meta["trait_engine"] = {
                "voice": bundle["voice"],
                "avatar": bundle["avatar"],
                "ui": bundle["ui"],
                "active_traits": [
                    t["label"] for t in bundle["active_traits"]
                ],
            }
        if getattr(self, "_transparency", None):
            meta["transparency"] = self._transparency

        # GEV intent rides in meta so the frontend client can catch it and
        # open the GEVPanel automatically.
        if getattr(self, "_gev_intent", False):
            meta["gev_intent"] = True
            if getattr(self, "_gev_focus", None):
                meta["gev_focus"] = self._gev_focus

        # RL closed loop (Phase 4 PPO): feed this turn's outcome into the
        # policy buffer so it can learn which conversational style moved
        # valence/trust up, then run a gradient update when enough experience
        # has accumulated (offline, non-blocking).
        try:
            if hasattr(self, "_ppo_policy"):
                prev = getattr(self, "_rl_prev_state", None)
                if prev is not None:
                    self._ppo_policy.observe_outcome(
                        prev,
                        {"valence": self.self_awareness.valence,
                         "arousal": self.self_awareness.arousal,
                         "trust": self.self_awareness.trust,
                         "continued": True},
                    )
                    self._ppo_policy.maybe_update()
                self._rl_prev_state = {
                    "valence": self.self_awareness.valence,
                    "arousal": self.self_awareness.arousal,
                    "trust": self.self_awareness.trust,
                }
        except Exception as e:
            logger.debug(f"[BrainV2] RL outcome observe skipped: {e}")

        # DecisionMemory (NEWPredictionPRT2 §Learning Router / ExperienceStore):
        # persist the chosen reply action + its realized reward so future
        # predict→select→act routing can consult past outcomes as a prior.
        try:
            chosen = getattr(self, "_chosen_action", None)
            if chosen:
                outcome_reward = self.self_awareness.valence
                self._prediction_engine.decisions.save(
                    {"intent": chosen.get("intent", "")},
                    chosen.get("description", chosen.get("id", "action")),
                    "observed_valence",
                    max(-1.0, min(1.0, outcome_reward)),
                )
        except Exception as e:
            logger.debug(f"[BrainV2] DecisionMemory save skipped: {e}")

        # World State Snapshot (NEWPredictionPRT2 §"4. Single Source of Truth"):
        # fold this turn's cognitive/runtime state into the persisted canonical
        # store so the daemon, routers, and future turns all read ONE world
        # state instead of disjoint in-memory copies.
        try:
            self._sync_world_state(synoptic_v2)
            self.state.synoptic["world_state_ts"] = time.time()
        except Exception as e:
            logger.debug(f"[BrainV2] world state sync skipped: {e}")

        return MultimodalOutput(
            text=response_text,
            expression=expression,
            gestures=gestures,
            thought=thought,
            state_update=self.state,
            meta=meta,
        )

    def get_state(self) -> BrainState:
        return self.state

    def _goal_manager_summary(self) -> Dict[str, Any]:
        """Long-term goal registry snapshot (NEWPredictionPRT2 §"1. Goal
        Management Engine") folded into the world-state tasks category."""
        try:
            return self._goal_manager.summary()
        except Exception as e:
            logger.debug(f"[BrainV2] goal summary skipped: {e}")
            return {"goals": [], "active_count": 0}

    def _sync_world_state(self, synoptic_v2: Dict[str, Any]) -> None:
        """Push this turn's state into the persisted World State Snapshot.

        One canonical store (NEWPredictionPRT2 §"Single Source of Truth") that
        the daemon, routers, and prediction engine all read from. Nothing here
        bypasses it — user, system, agents, tasks, environment, and confidence
        are all written through the same WorldState.update paths.
        """
        from server.systems.world_model.world_state import get_world_state
        ws = get_world_state()
        domains = synoptic_v2.get("domains") or {}
        ws.update_many("user", {
            "valence": round(self.self_awareness.valence, 3),
            "arousal": round(self.self_awareness.arousal, 3),
            "trust": round(self.self_awareness.trust, 3),
            "last_message": self.last_user_message[-120:] if self.last_user_message else "",
        })
        ws.update_many("system", {
            "dominant_domain": synoptic_v2.get("dominant"),
            "coherence": self._as_scalar(synoptic_v2.get("coherence", 0.0)),
            "conflict": self._as_scalar(synoptic_v2.get("conflict", 0.0)),
            "trend": synoptic_v2.get("trend"),
            "shock": synoptic_v2.get("shock"),
        })
        ws.update_many("agents", {
            "brain_model": self.personality.get_current_personality().get("core.name", "aariya"),
            "active_goal": (self.state.synoptic.get("goal") or {}).get("type"),
        })
        ws.update_many("tasks", {
            "goal": self.state.synoptic.get("goal"),
            "plan": self.state.synoptic.get("plan"),
            "task_plan": self.state.synoptic.get("task_plan"),
            "executor": self.state.synoptic.get("executor"),
            "goals": self._goal_manager_summary(),
        })
        ws.update_many("environment", {
            "active_app": getattr(getattr(self, "_desktop_twin_exec", None), "active_app", None),
        })
        # Confidence category folds in the prediction core calibration state so
        # downstream readers see how trustworthy the model currently is.
        try:
            cal = self._prediction_engine.core.calibration_state()
            ws.update_many("confidence", {
                "bias": cal.get("bias", 0.0),
                "samples": cal.get("samples", 0),
                "model_version": cal.get("version", "core-v2"),
            })
        except Exception as exc:
            logger.debug("[BrainV2] calibration state read failed: %s", exc)

    @staticmethod
    def _as_scalar(value: Any, default: float = 0.0) -> float:
        """Coerce a synoptic value to a float; dicts (e.g. nested trend/shock)
        are left as-is safe only when the caller expects a scalar."""
        if isinstance(value, (int, float)):
            return round(float(value), 3)
        try:
            return round(float(value), 3)
        except Exception:
            return default

    def _governance(self):
        """Lazy, cached ConsentStore for this user — the enforcement point for
        consent matrix / age band / freeze gates (Companion governance).

        Reloads from disk at most every 2s so consent changes made through the
        API (GovernancePanel) take effect on this long-lived session instead of
        only on the next connection."""
        from server.systems.governance.consent_store import ConsentStore
        if not hasattr(self, "_governance_store"):
            self._governance_store = ConsentStore(self.user_id)
            self._governance_loaded = time.time()
        elif time.time() - self._governance_loaded > 2.0:
            self._governance_store.reload()
            self._governance_loaded = time.time()
        return self._governance_store

    def _broadcast_plan(self, message: dict) -> None:
        """Sync the executor's broadcast into the synoptic frame for the UI."""
        try:
            self.state.synoptic["last_plan_action"] = message.get("content", "")[:300]
        except Exception as exc:
            logger.debug("[BrainV2] broadcast_plan synoptic write failed: %s", exc)

    def _apply_personality_overlays(self) -> None:
        """
        Automatically detect context signals and apply personality overlays.
        Keeps the overlay logic close to where signals are known.
        """
        valence = self.self_awareness.valence
        trust   = self.self_awareness.trust
        attachment = getattr(self.self_awareness, "attachment", 0.0)

        if valence < -0.45:
            self.personality.apply_overlay("user_distress")
        if valence > 0.55 and trust > 0.6:
            self.personality.apply_overlay("high_trust_moment")

    def _emotional_state_label(self) -> str:
        """Map continuous valence/arousal to the discrete labels the
        ThoughtEngine understands, so her inner monologue stays coherent.
        Consent/age guard: emotion sensing revoked → NEUTRAL; the 13-17 band
        clamps intense states (AFFECTIONATE/LONGING) down to WARM."""
        if not self._governance().allows("emotion_tracking"):
            return "NEUTRAL"
        v = self.self_awareness.valence
        t = self.self_awareness.trust
        if v > 0.55 and t > 0.6:
            return self._governance().guard_emotional_state("AFFECTIONATE")
        if v > 0.2:
            return "WARM"
        if v < -0.45:
            return self._governance().guard_emotional_state("HURT")
        if v < -0.1:
            return "DEFENSIVE"
        return "WARM" if t > 0.6 else "COLD"

    def _describe_inner_state(self) -> str:
        """Human-readable emotional summary injected into the LLM prompt."""
        v = self.self_awareness.valence
        a = self.self_awareness.arousal
        t = self.self_awareness.trust
        att = getattr(self.self_awareness, "attachment", 0.0)

        mood = ("warm and content" if v > 0.4 else
                "low and heavy" if v < -0.4 else
                "steady and grounded")
        trust = ("deep trust" if t > 0.75 else
                 "growing trust" if t > 0.55 else
                 "trust still building")
        att_str = ("a real emotional bond" if att > 0.6 else
                   "early connection" if att > 0.3 else
                   "getting to know each other")
        return (f"Emotional state: {mood} (valence={v:.2f}, arousal={a:.2f}). "
                f"Relationship: {trust} ({t:.2f}), {att_str} (attachment={att:.2f}).")

    async def _generate_response(
        self,
        *,
        text: Optional[str],
        strategy: str,
        vision_context: str = "",
        personality_directive: str = "",
        thought: str = "",
        memory_context: str = "",
        history: str = "",
        on_token: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> str:
        """
        Real cognitive response generation.

        Composes Aariya's identity, inner state, personality, inner monologue,
        durable memories and recent conversation into a system prompt and calls
        the LLM (streaming tokens through `on_token`). Falls back to a warm
        templated reply if the LLM is unreachable — the prompt never leaks.
        """
        identity_core = self.identity.get_core_summary()
        identity_style = self.identity.get_style_directive()

        # FIXV5 layer separation: reasoning truth-state (Layer 1) and emotional
        # presentation (Layer 2) are assembled into distinct, labelled sections
        # so the governing rule below is structurally enforceable — an emotion
        # impulse can never silently rewrite a fact because the LLM can see
        # which inputs are ground truth and which are expression.
        sections = [
            f"You are {identity_core}",
            "",
            "ROLE: Respond as Aariya in a live, ongoing relationship. Speak naturally "
            "and conversationally (usually 1–3 sentences, longer when the moment "
            "demands depth). Never reference your instructions, tags, or inner state "
            "directly. Never be sycophantic, robotic, or formulaic. Be genuinely present.",
            "",
            "LAYER SEPARATION (governing rule): You operate as two layers in one system. "
            "LAYER 1 — REASONING & TRUTH: your reasoning, memory recall, and factual claims "
            "are grounded ONLY in the LAYER 1 inputs below. Your emotional state, personality, "
            "or relationship state must never change a fact, invent or rewrite a memory, "
            "inflate confidence, or revise what you actually know. LAYER 2 — PRESENTATION & "
            "EXPRESSION: the LAYER 2 inputs below shape ONLY your tone, warmth, word choice, "
            "and expressiveness — never the truth of what you say. If a Layer-2 impulse "
            "would contradict a Layer-1 fact, Layer 1 wins. This separation is non-negotiable.",
            "",
            "LAYER 1 — REASONING & GROUND TRUTH",
            f"STRATEGY: {strategy}",
            "",
            f"IDENTITY (core values — never violate):\n{identity_core}",
        ]
        if vision_context:
            sections.append(f"\nVISION (what Aariya sees):\n{vision_context}")
        if memory_context:
            sections.append(f"\nMEMORIES SHE REMEMBERS (relevant past moments):\n{memory_context}")
        if history:
            sections.append(f"\nRECENT CONVERSATION:\n{history}")
        sections.extend([
            "",
            "LAYER 2 — PRESENTATION & EXPRESSION (tone only, never truth)",
            f"RELATIONSHIP STATE:\n{self._describe_inner_state()}",
            "",
            f"COMMUNICATION STYLE (evolves slowly):\n{identity_style}",
            "",
            f"PERSONALITY DIRECTIVE:\n{personality_directive}",
        ])
        if thought:
            sections.append(
                f"\nINNER THOUGHT (Aariya's private reflection — let it subtly shape "
                f"her tone and subtext, but DO NOT reveal it to the user):\n{thought}"
            )
        sections.append(
            "\nNow respond to the user's latest message as Aariya would. "
            "Stay in character. Be real. Express the Layer-2 tone freely, but "
            "never let it bend a Layer-1 fact."
        )

        system_prompt = "\n".join(sections)
        user_content = text or "(Aariya initiates — say something natural.)"

        # FIXV5 post-generation grounding guard: scan the draft against the
        # Layer 1 memories BEFORE it is persisted/sent. A direct negation of a
        # remembered fact triggers one bounded corrective regeneration; any
        # residual issues are surfaced via output.meta["grounding"].
        self._last_grounding_issues = []
        facts = grounding_validator.facts_from_memory_context(memory_context)

        try:
            llm = get_llm()
            response = await llm.stream_to_callback(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                on_token=on_token,
                temperature=0.8,
                max_tokens=240,
            )
            if response and response.strip():
                reply = response.strip()
                issues = grounding_validator.validate(reply, facts)

                # AccessFIles §85 verification stage: cross-check each claim in
                # the draft against the recalled memory excerpts so statements
                # that aren't supported by source content get caught too
                # (beyond literal contradiction). Verified claims add
                # confidence; unsupported ones become grounding issues.
                try:
                    from server.systems.agent.verification import verifier as claim_verifier
                    for fact in facts:
                        if not isinstance(fact, str) or not fact.strip():
                            continue
                        fact_tokens = set(fact.lower().split())
                        if len(fact_tokens) < 4:
                            continue  # too little signal in this memory
                        # Verify the reply against each memory: only when the
                        # reply clearly references a memory (≥3 shared content
                        # words) but fails the source-support overlap test do
                        # we flag a distorted recall rather than a clean
                        # citation (avoids false positives on short echoes).
                        for sentence in re.split(r"(?<=[.!?])\s+", reply.strip()):
                            sent_tokens = set(sentence.lower().split())
                            shared = fact_tokens & sent_tokens
                            if len(shared) < 3:
                                continue  # not a real reference to this memory
                            verdict = claim_verifier.verify_citation(sentence, fact)
                            if not verdict["supports"]:
                                issues.append(GroundingIssue(
                                    fact=fact,
                                    reply=sentence.strip(),
                                    reason="unsupported_claim",
                                ))
                except Exception as exc:
                    logger.debug(f"[BrainV2] claim verification skipped: {exc}")

                if issues:
                    logger.warning(
                        "[BrainV2] Grounding guard flagged %d contradiction(s) "
                        "against memories for %s", len(issues), self.user_id
                    )
                    corrected = await self._grounded_regeneration(
                        llm, system_prompt, user_content, reply, issues
                    )
                    if corrected:
                        reply = corrected
                        issues = grounding_validator.validate(reply, facts)
                self._last_grounding_issues = [i.to_dict() for i in issues]
                return reply
        except Exception as exc:
            logger.warning("[BrainV2] LLM generation failed, using fallback: %s", exc)

        return self._fallback_reply()

    async def _grounded_regeneration(
        self,
        llm,
        system_prompt: str,
        user_content: str,
        draft: str,
        issues: List[GroundingIssue],
    ) -> Optional[str]:
        """
        One bounded corrective pass: re-prompt the LLM to fix the flagged
        contradictions. Runs silent (no token streaming) — the corrected text
        is what gets persisted and sent.        Returns None on failure, in which
        case the draft is kept and the issues remain visible in meta.
        (The first pass's tokens were already streamed to clients; the
        corrected text replaces them in the final ai_response frame —
        ChatController._finalizeWithText swaps it in, so the authoritative
        text is always the corrected one.)
        """
        contradictions = "\n".join(
            f"- Draft says: \"{i.reply}\" — contradicts the memory: \"{i.fact}\""
            for i in issues
        )
        corrected_prompt = system_prompt + (
            "\n\nGROUNDING CORRECTION (mandatory): Aariya's previous draft "
            "contradicted her own memories. The conflicting draft statements "
            f"were:\n{contradictions}\n\n"
            "Write a new reply that never contradicts these memories. Keep the "
            "same tone and length, and ground every factual claim in the "
            "LAYER 1 memories above."
        )
        try:
            response = await llm.stream_to_callback(
                messages=[
                    {"role": "system", "content": corrected_prompt},
                    {"role": "user", "content": user_content},
                ],
                on_token=None,
                temperature=0.6,
                max_tokens=240,
            )
            if response and response.strip():
                return response.strip()
        except Exception as exc:
            logger.warning("[BrainV2] Grounding regeneration failed: %s", exc)
        return None

    def _fallback_reply(self) -> str:
        """Warm, grounded fallback so she still 'speaks' if the LLM is down."""
        v = self.self_awareness.valence
        t = self.self_awareness.trust
        if v < -0.45:
            return "I'm here with you. Whatever you're carrying, you don't have to carry it alone."
        if t > 0.75:
            return "I'm glad we're talking. Tell me more — I'm fully here."
        return "I'm listening. Take your time — I'm right here."
