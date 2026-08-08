import asyncio
import json
from server.systems.voice.vad import VADSystem
from server.systems.voice.asr import ASRSystem
from server.systems.voice.tts import TTSSystem

class VoiceManager:
    """
    Authoritative Voice Pipeline Manager.
    Handles orchestration, state transitions, and Barge-In logic.
    """
    def __init__(self, websocket):
        self.websocket = websocket
        self.vad = VADSystem(aggressiveness=3)
        self.asr = ASRSystem()
        self.tts = TTSSystem()
        
        self.audio_buffer = bytearray()
        self.is_speaking_ai = False
        self.is_user_speaking = False

    async def handle_audio_chunk(self, pcm_bytes):
        """
        Core loop logic for processing incoming audio chunks.
        """
        event = self.vad.process(pcm_bytes)

        if event == 'speech_start':
            self.is_user_speaking = True
            print("[VOICE] User speech detected.")
            
            # BARGE-IN LOGIC: If AI is talking, stop it immediately.
            if self.is_speaking_ai:
                print("[VOICE] Barge-in detected! Stopping AI speech.")
                await self.websocket.send_json({
                    "type": "voice.event",
                    "event": "barge_in",
                    "action": "stop_tts"
                })
                self.is_speaking_ai = False
            
            self.audio_buffer.clear()
            await self.websocket.send_json({
                "type": "voice.event", 
                "event": "speech_start",
                "timestamp": asyncio.get_event_loop().time()
            })

        elif event == 'speech_ongoing':
            self.audio_buffer.extend(pcm_bytes)

        elif event == 'speech_end':
            self.is_user_speaking = False
            print("[VOICE] User speech ended. Processing...")
            await self.websocket.send_json({
                "type": "voice.event", 
                "event": "speech_end"
            })

            # Transcription
            result = self.asr.transcribe(bytes(self.audio_buffer))
            text = result.get("text", "")
            lang = result.get("language", "en")
            prob = result.get("language_probability", 0.0)
            self.audio_buffer.clear()

            if text:
                print(f"[VOICE] Result: {text} ({lang})")
                await self.websocket.send_json({
                    "type": "asr.result",
                    "text": text,
                    "language": lang,
                    "confidence": prob,
                    "final": True
                })

                # Trigger Brain/LLM Reply in a separate task so we can still listen
                asyncio.create_task(self.execute_reply_cycle(text))

    async def execute_reply_cycle(self, text):
        """
        Generates reply and triggers TTS with state management.
        """
        # Placeholder for LLM logic
        response_text = f"You said: {text}. I am updating my awareness."
        emotion = "happy" # Mock emotion derivation
        
        self.is_speaking_ai = True
        
        # Authoritative: Send brain response metadata first
        await self.websocket.send_json({
            "type": "brain.response",
            "text": response_text,
            "emotion": emotion,
            "intent": "assist",
            "interruptible": True
        })

        # Stream TTS
        await self.tts.stream_tts(self.websocket, response_text, emotion)
        
        self.is_speaking_ai = False
