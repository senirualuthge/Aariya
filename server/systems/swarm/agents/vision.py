"""
VisionAgent — FIXV4 Swarm Member
──────────────────────────────────
Interprets the VisionData payload arriving from the React frontend
(face detection + multimodal emotion confidence) and produces a
contextual observation string that is injected into the LLM system prompt.

If OPENAI_API_KEY is set and image_b64 is provided, the agent will
attempt a GPT-4V scene-description call for full contextual awareness
("I see you're at a desk with the lights dim…"). Otherwise it falls
back to emotion-inference mode using the structured VisionData fields.

Output is a string tagged [VISION] to distinguish from other agent outputs.
"""

import os
import asyncio
import logging
from typing import Any, Dict, Optional

from server.systems.swarm.agents.base import Agent

logger = logging.getLogger("aariya.swarm.vision")

_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


class VisionAgent(Agent):
    """
    Swarm agent that converts VisionData → contextual prompt modifier.
    Conforms to the `Agent` base interface: async act(state) -> dict.
    """

    name = "VisionAgent"

    def __init__(self):
        super().__init__("vision")

    async def act(self, state: Dict[str, Any]) -> dict:
        """
        Args:
            state: dict containing:
                - vision_data: dict (mapped from VisionData model)
                - image_b64:   Optional[str] raw frame
                - trust:       float

        Returns:
            {"agent": "vision", "context": str, "confidence": float}
        """
        vision_data: Optional[dict] = state.get("vision_data")
        image_b64: Optional[str]   = state.get("image_b64")
        trust: float                = state.get("trust", 0.5)

        if vision_data is None:
            return {"agent": "vision", "context": "", "confidence": 0.0}

        # ── Path A: Full scene description via GPT-4V (requires API key + image) ──
        if _OPENAI_API_KEY and image_b64:
            context = await self._describe_scene_gpt4v(image_b64, trust)
            if context:
                return {"agent": "vision", "context": f"[VISION] {context}", "confidence": 0.85}

        # ── Path B: Emotion inference from structured VisionData ──────────────
        context = self._infer_from_emotion_data(vision_data, trust)
        confidence = vision_data.get("face_confidence", 0.0)

        return {
            "agent":      "vision",
            "context":    f"[VISION] {context}" if context else "",
            "confidence": confidence,
        }

    # ── GPT-4V scene description ──────────────────────────────────────────────

    async def _describe_scene_gpt4v(self, image_b64: str, trust: float) -> str:
        """
        Call OpenAI GPT-4V to get a brief scene description.
        Gated: only runs if OPENAI_API_KEY is present.
        """
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=_OPENAI_API_KEY)

            trust_note = (
                "Be warm and personal." if trust > 0.6
                else "Be observational and neutral."
            )

            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Describe THIS scene in 1 sentence from an AI companion's perspective. "
                                f"Focus on the person's apparent state/environment. "
                                f"Max 25 words. {trust_note}"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                    ],
                }],
                max_tokens=60,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning(f"[VisionAgent] GPT-4V call failed: {e}")
            return ""

    # ── Emotion-inference mode (no API key) ───────────────────────────────────

    def _infer_from_emotion_data(self, vision_data: dict, trust: float) -> str:
        """
        Construct a natural-language sentence from the numerical VisionData fields.
        Example: "The user appears calm and positive (face confidence: 0.82)."
        """
        face_detected = vision_data.get("face_detected", False)
        if not face_detected:
            return ""

        face_valence    = vision_data.get("face_valence", 0.0)
        face_arousal    = vision_data.get("face_arousal", 0.0)
        face_confidence = vision_data.get("face_confidence", 0.0)

        if face_confidence < 0.3:
            # Low confidence — don't make false claims
            return "The user's face is visible but emotional state is unclear."

        # Valence descriptor
        if face_valence > 0.5:
            valence_str = "happy and positive"
        elif face_valence > 0.15:
            valence_str = "content"
        elif face_valence > -0.15:
            valence_str = "neutral"
        elif face_valence > -0.4:
            valence_str = "slightly subdued"
        else:
            valence_str = "distressed or upset"

        # Arousal descriptor
        if face_arousal > 0.6:
            arousal_str = "and energetic"
        elif face_arousal > 0.3:
            arousal_str = "and alert"
        else:
            arousal_str = "and calm"

        return (
            f"The user appears {valence_str} {arousal_str} "
            f"(visual confidence: {face_confidence:.0%})."
        )
