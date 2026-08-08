try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    print("[WARN] faster-whisper not installed. Using mock ASR.")

import os
import io
import numpy as np

class ASRSystem:
    def __init__(self, device="cpu", compute_type="int8"):
        if WHISPER_AVAILABLE:
            self.model_size = os.getenv("WHISPER_MODEL", "tiny.en")
            # Recommended size from documentation is "tiny.en" for better accuracy/speed balance
            print(f"[ASR] Loading Faster-Whisper model {self.model_size} on {device}...")
            try:
                self.model = WhisperModel(self.model_size, device=device, compute_type=compute_type, cpu_threads=4, num_workers=2)
                print("[ASR] Model loaded.")
            except Exception as e:
                print(f"[ASR] Failed to load model: {e}")
                self.model = None
        else:
            self.model = None

    def transcribe(self, audio_bytes, language="en"):
        """
        Transcribe audio bytes (PCM 16-bit, 16kHz, Mono).
        Returns: dict with text, language, language_probability, duration
        """
        if not self.model:
            return {"text": "Error: Model not loaded", "language": "en", "language_probability": 0.0, "duration": 0.0}

        try:
            # DOCUMENTED LOGIC: Convert int16 bytes to float32 numpy array
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            
            segments, info = self.model.transcribe(
                audio_array, 
                beam_size=3,
                best_of=3,
                vad_filter=True, # Use internal VAD filter for secondary check
                vad_parameters={
                    "min_silence_duration_ms": 300,
                    "speech_pad_ms": 100
                },
                language=language if not self.model_size.endswith(".en") else None
            )
            
            text = "".join(seg.text for seg in segments).strip()
            
            return {
                "text": text,
                "language": info.language,
                "language_probability": info.language_probability,
                "duration": info.duration
            }
            
        except Exception as e:
            print(f"[ASR] Transcription error: {e}")
            return {"text": "", "language": "en", "language_probability": 0.0, "duration": 0.0}
