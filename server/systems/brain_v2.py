import asyncio
import logging
# BUG #3 FIX: Optional was missing — caused NameError on startup
from typing import Optional, Callable, Awaitable

from server.protocol import MultimodalInput, MultimodalOutput, BrainState
from server.systems.self_awareness import SelfAwareness
from server.systems.theory_of_mind import TheoryOfMind
from server.systems.policy_router import PolicyRouter
from server.systems.emotion_behavior import EmotionBehavior
from server.systems.personality import PersonalitySystem
from server.systems.swarm.orchestrator import get_swarm_system
from server.systems.synoptic_aggregator import SynopticAggregator
from server.systems.narrative_engine import NarrativeEngine, NarrativeEvent
from server.systems.narrative_arcs import NarrativeArcSystem
from server.systems.meta_cognition import MetaCognitionEngine
from server.systems.goals import GoalArbitrator
from server.systems.self_knowledge import get_self_knowledge
from server.systems.identity_kernel import get_identity_kernel
from server.systems.thoughts import ThoughtEngine
from server.systems.memory.conversation_log import ConversationLog
from server.systems.llm import get_llm

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
        self.meta_cognition = MetaCognitionEngine()
        self.goal_arbitrator = GoalArbitrator()
        self.self_knowledge = get_self_knowledge()

        # ── Sentience modules ───────────────────────────────────────────────
        self.identity = get_identity_kernel()          # immutable core + mutable style
        self.thought_engine = ThoughtEngine()          # private inner monologue
        self.conversation = ConversationLog(user_id)   # durable conversational self

        # Continuity: resume emotional state from the last persisted snapshot
        # so a reconnect/restart doesn't reset her relationship to zero.
        last = self.conversation.last_state()
        if last:
            self.self_awareness.trust = float(last.get("trust", 0.5))
            self.self_awareness.valence = float(last.get("valence", 0.0))
            self.self_awareness.arousal = float(last.get("arousal", 0.0))
            self.self_awareness.attachment = float(last.get("attachment", 0.0))
            logger.debug("[BrainV2] Restored emotional continuity for %s "
                         "(trust=%.2f valence=%.2f)", user_id,
                         self.self_awareness.trust, self.self_awareness.valence)

        self.state = BrainState(
            personality=self.personality.get_current_personality()
        )
        self.self_awareness._last_trust = self.self_awareness.trust

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

        # 1. Sense: Update Theory of Mind from user emotion
        if input_data.emotion_valence is not None:
            self.theory_of_mind.update(
                input_data.emotion_valence,
                input_data.emotion_arousal or 0.0
            )

        # 2. Reflect: Update self-awareness based on interaction
        self.self_awareness.reflect(input_data, self.theory_of_mind)

        # 2.5. Narrative Memory tracking
        latest_text = input_data.text or (input_data.metadata.get("transcription") or "general interaction")
        event = NarrativeEvent(
            topic=latest_text,
            user_sentiment=self.self_awareness.valence,
            trust_delta=self.self_awareness.trust - getattr(self.self_awareness, "_last_trust", self.self_awareness.trust),
            intensity=self.self_awareness.arousal
        )
        self.self_awareness._last_trust = self.self_awareness.trust
        self.narrative_engine.add_event(event)

        shock = self.narrative_engine.compute_shock()
        self.narrative_arcs.evaluate_arcs(shock, event.topic)
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
        memory_context = self.conversation.recall_prompt(input_data.text or "")
        history = self.conversation.recent_prompt(limit=10)

        # 6. Act: Generate text incorporating vision context + personality + narrative arc
        personality_directive = self.personality.get_llm_directive()
        if dominant_arc:
            personality_directive += f"\n[Priority Arc: {dominant_arc.theme} (Intensity: {dominant_arc.intensity:.1f})]"

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

        # 7. Evolve personality slowly based on relationship signals, then
        #    persist so the drift survives restarts (continuity of self).
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

        # Aggregate synoptic
        synoptic_state = self.synoptic_aggregator.aggregate_synoptic(swarm_activations)
        self._last_synoptic_state = synoptic_state  # Save for meta-cognition next turn

        self.state.synoptic = {
            "dominant_domain": synoptic_state.dominant_domain,
            "coherence": synoptic_state.coherence,
            "conflict": synoptic_state.conflict,
            "domains": synoptic_state.domains
        }
        self.state.planetary = self.synoptic_aggregator.synoptic_to_planets(synoptic_state)

        logger.debug(f"[BrainV2] Personality: {self.personality.describe()}")

        return MultimodalOutput(
            text=response_text,
            expression=expression,
            gestures=gestures,
            thought=thought,
            state_update=self.state,
            meta={"rag": rag_trace} if rag_trace else {}
        )

    def get_state(self) -> BrainState:
        return self.state

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
        ThoughtEngine understands, so her inner monologue stays coherent."""
        v = self.self_awareness.valence
        t = self.self_awareness.trust
        if v > 0.55 and t > 0.6:
            return "AFFECTIONATE"
        if v > 0.2:
            return "WARM"
        if v < -0.45:
            return "HURT"
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
                return response.strip()
        except Exception as exc:
            logger.warning("[BrainV2] LLM generation failed, using fallback: %s", exc)

        return self._fallback_reply()

    def _fallback_reply(self) -> str:
        """Warm, grounded fallback so she still 'speaks' if the LLM is down."""
        v = self.self_awareness.valence
        t = self.self_awareness.trust
        if v < -0.45:
            return "I'm here with you. Whatever you're carrying, you don't have to carry it alone."
        if t > 0.75:
            return "I'm glad we're talking. Tell me more — I'm fully here."
        return "I'm listening. Take your time — I'm right here."
