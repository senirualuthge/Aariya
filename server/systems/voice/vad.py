try:
    import webrtcvad
    VAD_AVAILABLE = True
except ImportError:
    VAD_AVAILABLE = False
    print("[WARN] webrtcvad not installed. Using mock VAD.")

import collections
import sys

class VADSystem:
    def __init__(self, aggressiveness=3, sample_rate=16000, frame_ms=20):
        if VAD_AVAILABLE:
            self.vad = webrtcvad.Vad(aggressiveness)
        else:
            self.vad = None
            
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        # PCM 16-bit Mono: sample_rate * ms / 1000 * 2 bytes per sample
        self.frame_size = int(sample_rate * frame_ms / 1000) * 2 
        self.buffer = bytearray()
        self.triggered = False
        
        # authoritative states from documentation
        self.history = collections.deque(maxlen=10) # 200ms window

    def process(self, chunk):
        """
        Process a chunk of audio.
        Returns: 'speech_start', 'speech_end', 'speech_ongoing', or None
        """
        self.buffer.extend(chunk)
        
        # Process all available full frames in the buffer
        result = None
        while len(self.buffer) >= self.frame_size:
            frame = bytes(self.buffer[:self.frame_size])
            del self.buffer[:self.frame_size]
            
            if VAD_AVAILABLE:
                is_speech = self.vad.is_speech(frame, self.sample_rate)
            else:
                is_speech = False # Default to silence in mock mode
                
            self.history.append(is_speech)
            
            # Smoothing logic
            ratio = sum(self.history) / len(self.history) if self.history else 0
            
            if not self.triggered:
                if ratio > 0.8:  # speech_start threshold
                    self.triggered = True
                    result = 'speech_start'
            else:
                if ratio < 0.2:  # speech_end threshold
                    self.triggered = False
                    result = 'speech_end'
                else:
                    # If we already have a start/end in this batch, return it, 
                    # otherwise mark as ongoing if we are triggered.
                    if not result:
                        result = 'speech_ongoing'
        
        return result
