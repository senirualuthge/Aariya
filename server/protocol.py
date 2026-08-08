from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone


# BUG #8 FIX: unified protocol — reconciles §4.4 spec, §8 WebSocket JSON examples,
# and the working MultimodalInput/Output used by brain_v2.py.
# Three schemas are kept here with clear naming:
#   - MultimodalInput / MultimodalOutput  → used by BrainV2 internally
#   - ClientInput / ServerOutput          → §4.4 / §8 wire protocol (React & Unity)
#   - BrainState                          → shared state model


# ── Internal brain models (used by brain_v2.py) ──────────────────────────────

class BrainState(BaseModel):
    valence: float = 0.0
    arousal: float = 0.0
    trust: float = 0.5
    attachment: float = 0.0
    personality: Dict[str, float] = {}
    current_mode: str = "balanced"
    # Canonical discrete emotion label (joy/calm/sadness/fear/neutral) so
    # clients get real emotion tints instead of re-deriving from the
    # continuous valence/arousal axes. Fed from the expression computed in
    # BrainV2.process() via the EXPRESSION_TO_EMOTION mapping.
    emotion: str = "neutral"
    # BUG #19 FIX: use timezone-aware UTC datetime to avoid naive-datetime
    # comparison bugs with PostgreSQL timestamps
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    synoptic: Dict[str, Any] = {}
    planetary: List[Dict[str, Any]] = []
    security: Dict[str, Any] = {}


class MultimodalInput(BaseModel):
    text: Optional[str] = None
    audio_b64: Optional[str] = None
    image_b64: Optional[str] = None
    emotion_valence: Optional[float] = None
    emotion_arousal: Optional[float] = None
    metadata: Dict[str, Any] = {}


class MultimodalOutput(BaseModel):
    text: str
    audio_url: Optional[str] = None
    expression: str = "neutral"
    gestures: List[str] = []
    thought: Optional[str] = None
    state_update: Optional[BrainState] = None
    meta: Dict[str, Any] = {}


# ── Wire protocol models (§4.4 / §8 — used by React, Unity, WebSocket) ───────

class VisionData(BaseModel):
    face_detected: bool = False
    emotion: Dict[str, float] = {}
    face_valence: float = 0.0
    face_arousal: float = 0.0
    voice_valence: float = 0.0
    voice_arousal: float = 0.0
    text_sentiment: float = 0.0
    face_confidence: float = 0.0
    voice_confidence: float = 0.0
    text_confidence: float = 0.0


class ClientInput(BaseModel):
    type: str = "input.multimodal"
    timestamp: int
    text: Optional[str] = None
    audio: Optional[str] = None          # base64 PCM
    vision: Optional[VisionData] = None
    lifecycle: Optional[str] = None      # "connect" | "update" | "disconnect" | "ping"


class WireBrainState(BaseModel):
    """BrainState as sent over the wire — matches §8 ServerOutput JSON."""
    personality: Dict[str, float] = {}
    emotion_target: Dict[str, Any] = {}
    thought_process: str = ""
    trust_score: float = 0.5
    social_intent: str = "LISTENING"
    social_action: str = "SUPPORTIVE"
    swarm_activations: Dict[str, Any] = {}
    synoptic: Dict[str, Any] = {}
    planetary: List[Dict[str, Any]] = []
    security: Dict[str, Any] = {}

class ServerOutput(BaseModel):
    type: str = "state.update"
    brain_state: WireBrainState
    response_text: Optional[str] = None
    voice_stream: Optional[str] = None   # base64 audio
    directives: List[str] = []
    meta: Dict[str, Any] = {}