# AI Girl — Improvement Code Implementations

---

## 1. Dynamic Text Confidence Weighting

**File:** `server/systems/emotion_fusion.py`

Replace the hardcoded `text_confidence = 0.9` with a dynamic signal based on message length, sentiment polarity strength, and punctuation intensity.

```python
# server/systems/emotion_fusion.py

import math

def compute_text_confidence(text: str, sentiment_score: float) -> float:
    """
    Dynamic text confidence — short/ambiguous messages get lower weight.
    
    Factors:
      - Token length:        longer = more signal
      - Polarity strength:   extreme sentiment = clearer signal
      - Punctuation:         !! / ??? = emphasis boost
    """
    if not text or not text.strip():
        return 0.0

    # 1. Token length factor (sigmoid — plateaus around 20+ words)
    word_count = len(text.split())
    length_factor = 1 / (1 + math.exp(-0.3 * (word_count - 6)))
    # word_count=1  → ~0.18
    # word_count=6  → ~0.50
    # word_count=20 → ~0.88

    # 2. Polarity strength (how far from neutral is the sentiment?)
    polarity_factor = min(abs(sentiment_score) * 1.5, 1.0)

    # 3. Punctuation emphasis (!! or ??? = user is emphasizing)
    exclaim_count = text.count('!') + text.count('?')
    punct_boost = min(exclaim_count * 0.05, 0.15)

    # Combine — base weight 0.4, max 0.95
    confidence = 0.4 + (length_factor * 0.35) + (polarity_factor * 0.15) + punct_boost
    return round(min(confidence, 0.95), 3)


def fuse_emotions(
    face_valence: float, face_conf: float,
    audio_valence: float, audio_conf: float,
    text_valence: float, text: str, sentiment_score: float,
    eps: float = 1e-6
) -> dict:
    """
    Confidence-weighted multimodal emotion fusion.
    Previously text_conf was hardcoded 0.9 — now computed dynamically.
    """
    text_conf = compute_text_confidence(text, sentiment_score)

    total_conf = face_conf + audio_conf + text_conf + eps

    final_valence = (
        face_valence  * face_conf  +
        audio_valence * audio_conf +
        text_valence  * text_conf
    ) / total_conf

    return {
        "final_valence": round(final_valence, 4),
        "text_confidence": text_conf,
        "dominant_signal": max(
            [("face", face_conf), ("audio", audio_conf), ("text", text_conf)],
            key=lambda x: x[1]
        )[0]
    }
```

---

## 2. Contradiction Detection — Intensity Mismatch

**File:** `server/systems/contradiction_detector.py`

Extend angular distance detection with a magnitude mismatch component — catches cases where face shows mild happiness but voice is screaming (or vice versa).

```python
# server/systems/contradiction_detector.py

import numpy as np

class ContradictionDetector:
    def __init__(self):
        self.ema_contradiction = 0.0
        self.EMA_ALPHA = 0.3

    def _angular_distance(self, vec_a: tuple, vec_b: tuple) -> float:
        """Original direction mismatch (0=aligned, 2=opposite)."""
        a = np.array(vec_a, dtype=float)
        b = np.array(vec_b, dtype=float)
        norm_a, norm_b = np.linalg.norm(a), np.linalg.norm(b)
        if norm_a < 1e-6 or norm_b < 1e-6:
            return 0.0
        cos_sim = np.dot(a, b) / (norm_a * norm_b)
        return 1.0 - float(np.clip(cos_sim, -1, 1))

    def _magnitude_mismatch(self, vec_a: tuple, vec_b: tuple) -> float:
        """
        NEW: Intensity mismatch — same direction but very different magnitudes.
        Example: face mildly happy (0.2, 0.1) but voice intense (0.8, 0.9)
        Returns 0.0 (no mismatch) to 1.0 (extreme intensity difference).
        """
        mag_a = np.linalg.norm(vec_a)
        mag_b = np.linalg.norm(vec_b)
        if mag_a < 1e-6 and mag_b < 1e-6:
            return 0.0
        max_mag = max(mag_a, mag_b, 1e-6)
        # Normalize difference relative to the stronger signal
        mismatch = abs(mag_a - mag_b) / max_mag
        # Only flag when BOTH signals are strong enough to be meaningful
        min_signal_strength = min(mag_a, mag_b)
        if min_signal_strength < 0.2:
            mismatch *= 0.4  # Dampen when one signal is weak/neutral
        return float(np.clip(mismatch, 0.0, 1.0))

    def detect(
        self,
        face_valence: float, face_arousal: float,
        audio_valence: float, audio_arousal: float,
        direction_weight: float = 0.6,
        intensity_weight: float = 0.4
    ) -> dict:
        """
        Combined contradiction score:
          - direction mismatch (original): are they pointing opposite ways?
          - intensity mismatch (NEW):      do they have wildly different magnitudes?
        """
        face_vec  = (face_valence,  face_arousal)
        audio_vec = (audio_valence, audio_arousal)

        direction_score = self._angular_distance(face_vec, audio_vec)
        intensity_score = self._magnitude_mismatch(face_vec, audio_vec)

        raw_contradiction = (
            direction_score * direction_weight +
            intensity_score * intensity_weight
        )

        # EMA smoothing — prevents single-frame false positives
        self.ema_contradiction = (
            0.7 * self.ema_contradiction +
            0.3 * raw_contradiction
        )

        state = {
            "raw": round(raw_contradiction, 4),
            "ema": round(self.ema_contradiction, 4),
            "direction_score": round(direction_score, 4),
            "intensity_score": round(intensity_score, 4),
            "suspicious": self.ema_contradiction > 0.6,
            "force_defensive": self.ema_contradiction > 0.7,
        }

        # Dashboard hint — what type of contradiction is it?
        if direction_score > intensity_score:
            state["contradiction_type"] = "direction"   # saying vs. feeling
        else:
            state["contradiction_type"] = "intensity"   # suppressing vs. performing

        return state
```

---

## 3. Episodic Memory with Vector Search

**File:** `server/systems/memory/episodic_memory.py`

Adds a mid-layer between short-term (last 20 turns) and long-term (personality EMA) — memorable moments with semantic retrieval via ChromaDB.

**Install:**
```bash
pip install chromadb sentence-transformers
```

```python
# server/systems/memory/episodic_memory.py

import chromadb
from chromadb.config import Settings
import hashlib
import time
from typing import Optional

class EpisodicMemory:
    """
    Stores semantically significant moments from conversations.
    Retrieves them mid-conversation when context is relevant.

    Memory tiers:
      Short-term  → last 20 turns (existing, in Redis)
      Episodic    → THIS — memorable moments, vector search
      Long-term   → personality EMA (existing, in SQLite)
    """

    # Only store turns above this emotional significance threshold
    SIGNIFICANCE_THRESHOLD = 0.45

    def __init__(self, user_id: str, persist_path: str = "./data/episodic"):
        self.user_id = user_id
        self.client = chromadb.PersistentClient(
            path=persist_path,
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            name=f"user_{user_id}_episodes",
            metadata={"hnsw:space": "cosine"}
        )

    def _significance_score(
        self,
        valence: float,
        arousal: float,
        trust_delta: float,
        contradiction_ema: float
    ) -> float:
        """
        How memorable is this moment?
        High arousal, trust change, or contradiction = memorable.
        """
        emotional_intensity = abs(valence) * 0.4 + arousal * 0.4
        trust_importance    = abs(trust_delta) * 10.0          # small deltas, amplified
        contradiction_flag  = contradiction_ema * 0.3

        return min(emotional_intensity + trust_importance + contradiction_flag, 1.0)

    def maybe_store(
        self,
        user_text: str,
        ai_response: str,
        valence: float,
        arousal: float,
        trust_delta: float,
        contradiction_ema: float,
        social_intent: str,
        metadata: Optional[dict] = None
    ) -> bool:
        """
        Conditionally stores a turn as an episodic memory.
        Returns True if stored, False if below significance threshold.
        """
        score = self._significance_score(valence, arousal, trust_delta, contradiction_ema)
        if score < self.SIGNIFICANCE_THRESHOLD:
            return False

        timestamp = int(time.time())
        doc_id = hashlib.md5(f"{self.user_id}{timestamp}{user_text[:30]}".encode()).hexdigest()

        # Store the episode
        self.collection.add(
            ids=[doc_id],
            documents=[f"User: {user_text}\nAI: {ai_response}"],
            metadatas=[{
                "timestamp": timestamp,
                "valence": round(valence, 3),
                "arousal": round(arousal, 3),
                "trust_delta": round(trust_delta, 4),
                "significance": round(score, 3),
                "social_intent": social_intent,
                **(metadata or {})
            }]
        )
        return True

    def recall(
        self,
        current_text: str,
        n_results: int = 3,
        min_significance: float = 0.0
    ) -> list[dict]:
        """
        Retrieve relevant episodic memories for the current context.
        Call this before each LLM prompt to inject relevant history.
        """
        if self.collection.count() == 0:
            return []

        results = self.collection.query(
            query_texts=[current_text],
            n_results=min(n_results, self.collection.count()),
            where={"significance": {"$gte": min_significance}} if min_significance > 0 else None
        )

        memories = []
        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i]
            memories.append({
                "text": doc,
                "significance": meta.get("significance", 0),
                "timestamp": meta.get("timestamp", 0),
                "valence": meta.get("valence", 0),
                "social_intent": meta.get("social_intent", ""),
            })

        # Sort by relevance * recency
        memories.sort(key=lambda m: m["significance"], reverse=True)
        return memories

    def format_for_prompt(self, memories: list[dict]) -> str:
        """
        Formats retrieved memories as a prompt injection block.
        Insert this into your system prompt before each LLM call.
        """
        if not memories:
            return ""

        lines = ["[Relevant memories from past conversations:]"]
        for m in memories:
            time_ago = int((time.time() - m["timestamp"]) / 3600)
            time_str = f"{time_ago}h ago" if time_ago < 48 else f"{time_ago // 24}d ago"
            lines.append(f"- ({time_str}, mood: {m['valence']:+.1f}) {m['text'][:200]}")

        return "\n".join(lines)
```

**Integration in `server/main.py`:**

```python
# In your WebSocket handler, before building the LLM prompt:

memories = episodic_memory.recall(current_text=msg.text, n_results=3)
memory_context = episodic_memory.format_for_prompt(memories)

system_prompt = f"""
You are Aariya, an emotionally intelligent AI companion.

{memory_context}

Current personality: warmth={personality.warmth:.2f}, energy={personality.energy:.2f}
Trust level: {trust_score:.2f} ({trust_tier})
"""

# After getting the response, maybe store it:
episodic_memory.maybe_store(
    user_text=msg.text,
    ai_response=response_text,
    valence=final_valence,
    arousal=final_arousal,
    trust_delta=trust_delta,
    contradiction_ema=contradiction.ema,
    social_intent=social_intent
)
```

---

## 4. Voice Pipeline — Faster STT + Instant Barge-In

### 4a. Switch to `tiny.en` for lower latency

**File:** `server/systems/voice/asr.py`

```python
# server/systems/voice/asr.py

from faster_whisper import WhisperModel
import os

# Choose model based on env — default tiny.en (~40% faster than base, English-only)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "tiny.en")

# "tiny.en"  → ~150ms, English only     ← recommended default
# "base"     → ~280ms, multilingual
# "base.en"  → ~220ms, English only
# "small.en" → ~450ms, best accuracy

model = WhisperModel(
    WHISPER_MODEL,
    device="cpu",
    compute_type="int8",
    cpu_threads=4,           # Use multiple cores
    num_workers=2            # Parallel preprocessing
)

def transcribe(audio_bytes: bytes, language: str = "en") -> dict:
    """
    Transcribe audio with timing info for barge-in coordination.
    Returns text + confidence + duration estimate.
    """
    segments, info = model.transcribe(
        audio_bytes,
        language=language if not WHISPER_MODEL.endswith(".en") else None,
        beam_size=3,          # Reduced from default 5 — faster, minimal quality loss
        best_of=3,
        vad_filter=True,      # Built-in VAD — skip silent chunks
        vad_parameters={
            "min_silence_duration_ms": 300,
            "speech_pad_ms": 100
        }
    )

    text_parts = []
    for segment in segments:
        text_parts.append(segment.text.strip())

    return {
        "text": " ".join(text_parts).strip(),
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration
    }
```

### 4b. Instant Client-Side Barge-In

**File:** `src/systems/VoicePipeline.js` (React/Path A)

```javascript
// src/systems/VoicePipeline.js

class VoicePipeline {
    constructor(socket) {
        this.socket = socket;
        this.audioContext = null;
        this.currentSource = null;   // Currently playing TTS audio
        this.isPlaying = false;
        this.vadActive = false;
    }

    // Called when TTS audio arrives from server
    async playTTSAudio(base64Audio) {
        this.audioContext = this.audioContext || new AudioContext();
        const arrayBuffer = Uint8Array.from(atob(base64Audio), c => c.charCodeAt(0)).buffer;
        const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);

        const source = this.audioContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(this.audioContext.destination);

        this.currentSource = source;
        this.isPlaying = true;

        source.onended = () => {
            this.isPlaying = false;
            this.currentSource = null;
        };

        source.start(0);
    }

    // VAD fires — user is speaking while AI is talking
    handleVADSpeechStart() {
        if (!this.isPlaying) return;

        // INSTANT client-side stop — don't wait for server round-trip
        this._stopPlaybackNow();

        // Then notify server to cancel TTS generation
        this.socket.send(JSON.stringify({
            type: "lifecycle",
            event: "interrupt",
            timestamp: Date.now()
        }));
    }

    _stopPlaybackNow() {
        if (this.currentSource) {
            try {
                this.currentSource.stop(0);          // Stop immediately at t=0
            } catch (_) { /* already stopped */ }
            this.currentSource.disconnect();
            this.currentSource = null;
        }
        this.isPlaying = false;
    }
}
```

**File:** `Unity/Scripts/VoicePipelineController.cs` (Unity/Path B)

```csharp
// Unity/Scripts/VoicePipelineController.cs

using UnityEngine;

public class VoicePipelineController : MonoBehaviour
{
    [Header("References")]
    public AudioSource ttsAudioSource;
    public AIStateReceiver aiStateReceiver;

    private bool _isPlayingTTS = false;

    // Called by VAD detection system when speech is detected
    public void OnVADSpeechDetected()
    {
        if (!_isPlayingTTS) return;

        // Stop audio IMMEDIATELY — before any server round-trip
        StopTTSInstant();

        // Notify server to cancel generation
        aiStateReceiver.SendInterrupt();

        Debug.Log("[VoicePipeline] Barge-in: stopped TTS instantly");
    }

    public void OnTTSAudioReceived(AudioClip clip)
    {
        ttsAudioSource.clip = clip;
        ttsAudioSource.Play();
        _isPlayingTTS = true;
    }

    private void StopTTSInstant()
    {
        ttsAudioSource.Stop();
        ttsAudioSource.clip = null;
        _isPlayingTTS = false;
    }

    // Poll for completion
    private void Update()
    {
        if (_isPlayingTTS && !ttsAudioSource.isPlaying)
            _isPlayingTTS = false;
    }
}
```

---

## 5. Trust-Aware Blink + Startle Animation

### 5a. Trust-Aware Blink Rate

**File:** `src/systems/BlinkSystem.jsx` (React/Path A)

```javascript
// src/systems/BlinkSystem.jsx

/**
 * Blink interval now driven by BOTH arousal AND trust tier.
 *
 * Arousal:      high arousal = faster blinking (anxiety, excitement)
 * Trust:        low trust = slight increase (nervous/guarded)
 *               high trust = slight decrease (comfortable, focused)
 * Attraction:   high valence + high trust = minimal blinking (engaged)
 */
export function getBlinkInterval(arousal, trustScore, valence) {
    const BASE_MIN = 1500;   // ms — maximum rate (very nervous)
    const BASE_MAX = 5000;   // ms — minimum rate (very calm)

    // Arousal component (original behavior)
    const arousalInterval = lerp(BASE_MAX, BASE_MIN, arousal);

    // Trust modifier
    // Low trust (<0.3) = +20% faster (guarded/nervous)
    // High trust+valence (>0.7, valence>0.5) = -25% slower (comfortable/attracted)
    let trustModifier = 1.0;
    if (trustScore < 0.3) {
        trustModifier = 0.80;   // faster
    } else if (trustScore > 0.7 && valence > 0.5) {
        trustModifier = 1.25;   // slower — engaged, comfortable
    }

    const interval = arousalInterval * trustModifier;

    // Add ±15% natural jitter
    const jitter = interval * (0.85 + Math.random() * 0.30);
    return Math.round(Math.max(1200, Math.min(6000, jitter)));
}

function lerp(a, b, t) {
    return a + (b - a) * Math.max(0, Math.min(1, t));
}
```

**File:** `Unity/Scripts/BlinkController.cs` (Unity/Path B)

```csharp
// Unity/Scripts/BlinkController.cs  — replace getNextBlinkInterval()

private float GetNextBlinkInterval()
{
    float baseInterval = Mathf.Lerp(maxBlinkInterval, minBlinkInterval, blinkRateMultiplier);

    // Trust modifier — received from Python Brain via WebSocket
    float trustModifier = 1.0f;
    if (currentTrustScore < 0.3f)
        trustModifier = 0.80f;   // nervous/guarded = faster
    else if (currentTrustScore > 0.7f && currentMoodValence > 0.5f)
        trustModifier = 1.25f;   // comfortable/attracted = slower

    float interval = baseInterval * trustModifier;

    // Natural jitter ±15%
    return interval * Random.Range(0.85f, 1.15f);
}
```

### 5b. Startle Animation on Arousal Spike

**File:** `Unity/Scripts/EmotionAnimationController.cs`

```csharp
// Unity/Scripts/EmotionAnimationController.cs

using UnityEngine;

public class EmotionAnimationController : MonoBehaviour
{
    [Header("Animator")]
    public Animator avatarAnimator;

    [Header("Startle Settings")]
    public float startleArousalDelta = 0.4f;    // Min spike to trigger startle
    public float startleCooldown = 3.0f;         // Seconds before can startle again

    private float _prevArousal = 0f;
    private float _lastStartleTime = -999f;

    // Call this every time new ServerOutput arrives
    public void OnEmotionUpdate(float newArousal, float newValence)
    {
        CheckForStartle(newArousal);
        _prevArousal = newArousal;
    }

    private void CheckForStartle(float newArousal)
    {
        float arousalDelta = newArousal - _prevArousal;
        bool cooldownPassed = Time.time - _lastStartleTime > startleCooldown;

        if (arousalDelta >= startleArousalDelta && cooldownPassed)
        {
            TriggerStartle(arousalDelta);
            _lastStartleTime = Time.time;
        }
    }

    private void TriggerStartle(float intensity)
    {
        // Trigger the startle animation — set up a Trigger param in your Animator
        avatarAnimator.SetTrigger("Startle");

        // Scale the startle intensity (drives blend weight in Animator)
        float normalizedIntensity = Mathf.Clamp01((intensity - startleArousalDelta) / 0.4f);
        avatarAnimator.SetFloat("StartleIntensity", normalizedIntensity);

        Debug.Log($"[EmotionAnim] Startle triggered! delta={intensity:F2}, intensity={normalizedIntensity:F2}");
    }
}
```

**Animator setup:** Add a `Startle` Trigger parameter and a `StartleIntensity` Float. Create a Startle state with your animation, transition from `Any State → Startle` on `Startle` trigger, then back to `Idle` on exit time.

---

## 6. Mid-Session Micro-Trust Signal

**File:** `server/systems/trust_system.py`

Adds a temporary per-session modifier that adjusts behavior for 2–4 turns after a significant event, without permanently shifting the long-term trust score.

```python
# server/systems/trust_system.py  — add MicroTrustSignal class

import time
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class MicroTrustSignal:
    """
    Short-lived trust modifier. Decays over turns.
    Does NOT affect long-term trust score — session-level only.

    Examples:
      - Single hostile message: delta=-0.3, duration=3 turns
      - Sudden contradiction:   delta=-0.2, duration=2 turns
      - Genuine compliment:     delta=+0.15, duration=2 turns
    """
    delta: float            # Positive or negative modifier
    turns_remaining: int    # How many turns until expired
    reason: str = ""        # For dashboard display
    created_at: float = field(default_factory=time.time)


class TrustSystem:
    def __init__(self, initial_score: float = 0.5):
        self.base_score = initial_score          # Long-term, persistent
        self._micro_signals: list[MicroTrustSignal] = []

    # ---- Long-term trust (existing, runs at session end) ---- #

    def update_long_term(
        self,
        session_valence: float,
        contradiction_history: float,
        continuity_bonus: float,
        violations: int,
        a=0.3, b=0.2, c=0.1, d=0.2
    ) -> float:
        delta = (
            a * session_valence
            + b * (1 - contradiction_history)
            + c * continuity_bonus
            - d * violations
        )
        self.base_score = max(0.0, min(1.0, self.base_score + delta))
        return self.base_score

    # ---- Micro-trust (NEW — mid-session, per-turn) ---- #

    def add_micro_signal(
        self,
        delta: float,
        duration_turns: int,
        reason: str = ""
    ):
        """
        Fire a short-lived trust modifier. Call this when events happen mid-session.

        Usage examples:
          trust.add_micro_signal(-0.3, 3, "hostile_message")
          trust.add_micro_signal(-0.2, 2, "sudden_contradiction")
          trust.add_micro_signal(+0.15, 2, "genuine_compliment")
        """
        self._micro_signals.append(
            MicroTrustSignal(delta=delta, turns_remaining=duration_turns, reason=reason)
        )

    def get_effective_trust(self) -> float:
        """
        Returns the current effective trust score = base + sum of active micro-signals.
        Call this (not base_score) when deciding AI behavior each turn.
        """
        micro_total = sum(s.delta for s in self._micro_signals)
        effective = self.base_score + micro_total
        return round(max(0.0, min(1.0, effective)), 4)

    def advance_turn(self):
        """
        Call once per turn to decay micro-signals.
        Expired signals are removed automatically.
        """
        active = []
        for signal in self._micro_signals:
            signal.turns_remaining -= 1
            if signal.turns_remaining > 0:
                active.append(signal)
        self._micro_signals = active

    def get_active_micro_signals(self) -> list[dict]:
        """For Rich dashboard display."""
        return [
            {
                "delta": s.delta,
                "turns_remaining": s.turns_remaining,
                "reason": s.reason
            }
            for s in self._micro_signals
        ]


# ---- Event detectors — call these in your main dialogue loop ---- #

def detect_micro_trust_events(
    trust: TrustSystem,
    user_text: str,
    contradiction_ema: float,
    valence: float,
    prev_contradiction_ema: float
):
    """
    Automatically fires micro-signals based on conversation events.
    Call this each turn before building the LLM prompt.
    """
    text_lower = user_text.lower().strip()

    # 1. Hostile / aggressive message
    hostile_keywords = {"hate", "stupid", "useless", "shut up", "idiot", "dumb", "ugly"}
    if any(kw in text_lower for kw in hostile_keywords):
        trust.add_micro_signal(-0.3, duration_turns=3, reason="hostile_message")

    # 2. Sudden contradiction spike (new spike, not ongoing)
    contradiction_spike = contradiction_ema - prev_contradiction_ema
    if contradiction_spike > 0.25:
        trust.add_micro_signal(-0.2, duration_turns=2, reason="contradiction_spike")

    # 3. Genuine positive engagement (high valence, not suspicious)
    if valence > 0.6 and contradiction_ema < 0.3:
        trust.add_micro_signal(+0.1, duration_turns=2, reason="genuine_positivity")
```

**Integration in `server/main.py`:**

```python
# Each turn in your WebSocket handler:

# 1. Detect and fire micro-signals
detect_micro_trust_events(
    trust=trust_system,
    user_text=msg.text,
    contradiction_ema=contradiction.ema,
    valence=final_valence,
    prev_contradiction_ema=prev_contradiction_ema
)

# 2. Use EFFECTIVE trust (not base) for all behavior decisions
effective_trust = trust_system.get_effective_trust()
trust_tier = get_trust_tier(effective_trust)    # Your existing tier lookup

# 3. Build prompt and gate behaviors using effective_trust
# ... LLM call ...

# 4. Advance micro-signal decay at end of turn
trust_system.advance_turn()
```

---

## 7. Infrastructure — `SIMPLE_MODE` + Dirty Personality Flag

### 7a. SIMPLE_MODE — Single SQLite backend

**File:** `server/infrastructure/db.py`

```python
# server/infrastructure/db.py

import os
import sqlite3
import json
import time

SIMPLE_MODE = os.getenv("SIMPLE_MODE", "false").lower() == "true"

class DB:
    """
    Unified database interface.
    SIMPLE_MODE=true  → SQLite only (zero external dependencies)
    SIMPLE_MODE=false → Redis + PostgreSQL + SQLite (production)
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.sqlite = sqlite3.connect(f"./data/{user_id}.db", check_same_thread=False)
        self._init_sqlite()

        if not SIMPLE_MODE:
            import redis, psycopg2
            self.redis = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
            self.pg = psycopg2.connect(os.getenv("POSTGRES_URL", ""))
        else:
            self.redis = None
            self.pg = None

    def _init_sqlite(self):
        self.sqlite.executescript("""
            CREATE TABLE IF NOT EXISTS identity (
                key TEXT PRIMARY KEY, value TEXT, updated_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY, data TEXT, updated_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT, event TEXT, data TEXT, ts INTEGER
            );
        """)
        self.sqlite.commit()

    # ---- Session state (trust score, contradiction EMA, etc.) ---- #

    def set_session(self, session_id: str, key: str, value):
        full_key = f"session:{session_id}:{key}"
        serialized = json.dumps(value)

        if SIMPLE_MODE or self.redis is None:
            self.sqlite.execute(
                "INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)",
                (full_key, serialized, int(time.time()))
            )
            self.sqlite.commit()
        else:
            self.redis.set(full_key, serialized, ex=86400)  # 24h TTL

    def get_session(self, session_id: str, key: str, default=None):
        full_key = f"session:{session_id}:{key}"

        if SIMPLE_MODE or self.redis is None:
            row = self.sqlite.execute(
                "SELECT value FROM sessions WHERE session_id = ?", (full_key,)
            ).fetchone()
            return json.loads(row[0]) if row else default
        else:
            val = self.redis.get(full_key)
            return json.loads(val) if val else default

    # ---- Identity (personality, trust base) ---- #

    def set_identity(self, key: str, value):
        self.sqlite.execute(
            "INSERT OR REPLACE INTO identity VALUES (?, ?, ?)",
            (key, json.dumps(value), int(time.time()))
        )
        self.sqlite.commit()

    def get_identity(self, key: str, default=None):
        row = self.sqlite.execute(
            "SELECT value FROM identity WHERE key = ?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else default

    # ---- Analytics ---- #

    def log_event(self, session_id: str, event: str, data: dict):
        if SIMPLE_MODE or self.pg is None:
            self.sqlite.execute(
                "INSERT INTO analytics (session_id, event, data, ts) VALUES (?, ?, ?, ?)",
                (session_id, event, json.dumps(data), int(time.time()))
            )
            self.sqlite.commit()
        else:
            with self.pg.cursor() as cur:
                cur.execute(
                    "INSERT INTO events (session_id, event, data, ts) VALUES (%s, %s, %s, %s)",
                    (session_id, event, json.dumps(data), int(time.time()))
                )
            self.pg.commit()
```

**.env additions:**
```bash
# Add to .env
SIMPLE_MODE=true      # Use for local dev — no Redis/PostgreSQL needed
# SIMPLE_MODE=false   # Use for production
```

### 7b. Dirty Personality Flag — Stop Sending Unchanged Personality

**File:** `server/systems/personality.py`

```python
# server/systems/personality.py  — add dirty tracking

class PersonalitySystem:
    def __init__(self, initial: dict = None):
        self._personality = initial or {
            "warmth": 0.3,
            "energy": 0.5,
            "assertiveness": 0.5,
            "formality": 0.4
        }
        self._dirty = True      # True = has unsent changes
        self._last_sent = {}    # Last values sent to client

    @property
    def personality(self):
        return self._personality.copy()

    def update(self, avg_valence: float, avg_arousal: float, volatility: float):
        """EMA drift — existing logic, now sets dirty flag on change."""
        alpha = 0.01

        warmth_target      = 0.6 * avg_valence + 0.4 * (1 - volatility)
        energy_target      = avg_arousal
        assertiveness_target = 1 - volatility

        new_warmth = (1 - alpha) * self._personality["warmth"] + alpha * warmth_target
        new_warmth = max(-0.4, min(0.6, new_warmth))

        new_energy = (1 - alpha) * self._personality["energy"] + alpha * energy_target
        new_assertiveness = (1 - alpha) * self._personality["assertiveness"] + alpha * assertiveness_target

        new_personality = {
            "warmth":        round(new_warmth, 4),
            "energy":        round(new_energy, 4),
            "assertiveness": round(new_assertiveness, 4),
            "formality":     self._personality["formality"]    # not updated here
        }

        if new_personality != self._personality:
            self._personality = new_personality
            self._dirty = True

    def get_for_transmission(self) -> dict | None:
        """
        Returns personality dict ONLY if changed since last send.
        Returns None if unchanged — skip including in ServerOutput.
        
        Usage in main.py:
          personality_payload = personality_system.get_for_transmission()
          # Include in response only if not None
        """
        if not self._dirty:
            return None

        self._last_sent = self._personality.copy()
        self._dirty = False
        return self._personality.copy()
```

**Integration in `server/main.py`:**

```python
# When building ServerOutput each turn:

personality_update = personality_system.get_for_transmission()

response = {
    "type": "ai_response",
    "text": response_text,
    "emotion": emotion_target,
    "trust_score": effective_trust,
    "status": { "thinking": False, "speaking": True },
    # Only include personality if it changed (saves bandwidth on every voice turn)
    **({"personality": personality_update} if personality_update else {})
}
```

---

## Summary

| # | Improvement | Files Changed |
|---|---|---|
| 1 | Dynamic text confidence | `server/systems/emotion_fusion.py` |
| 2 | Intensity mismatch contradiction | `server/systems/contradiction_detector.py` |
| 3 | Episodic vector memory | `server/systems/memory/episodic_memory.py` |
| 4 | Faster Whisper + instant barge-in | `server/systems/voice/asr.py`, `VoicePipeline.js`, `VoicePipelineController.cs` |
| 5 | Trust-aware blink + startle | `BlinkSystem.jsx`, `BlinkController.cs`, `EmotionAnimationController.cs` |
| 6 | Mid-session micro-trust | `server/systems/trust_system.py` |
| 7 | SIMPLE_MODE + dirty personality | `server/infrastructure/db.py`, `server/systems/personality.py` |

**Recommended implementation order:** 7 (infrastructure first, lowest risk) → 6 (micro-trust) → 1 (emotion fusion) → 2 (contradiction) → 4 (voice) → 5 (animation) → 3 (episodic memory — needs ChromaDB setup)
