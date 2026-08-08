// src/systems/AudioFFTSystem.tsx
/**
 * Audio FFT System (Migrated to Triple Loop)
 * 
 * Runs in the Sensor Loop (8-15 Hz)
 * Extracts audio features and maps to emotion
 */

import { useEffect, useRef } from 'react';
import { tripleLoopRuntime } from '../core/tripleLoopRuntime';
import { stateThrottle } from '../core/stateThrottle';

export default function AudioFFTSystem() {
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const dataArrayRef = useRef<Uint8Array | null>(null);
  
  useEffect(() => {
    // Initialize audio context
    navigator.mediaDevices.getUserMedia({ audio: true, video: false })
      .then(stream => {
        const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
        const analyser = audioContext.createAnalyser();
        
        // FFT size from runtime config (would be tier-specific)
        analyser.fftSize = 2048;
        
        const source = audioContext.createMediaStreamSource(stream);
        source.connect(analyser);
        
        audioContextRef.current = audioContext;
        analyserRef.current = analyser;
        dataArrayRef.current = new Uint8Array(analyser.frequencyBinCount);
        
        console.log('[Audio FFT] Initialized');
      })
      .catch(err => {
        console.warn('[Audio FFT] Access denied:', err);
        // Set neutral emotion
        stateThrottle.queueUpdate({
          audioEmotion: { valence: 0, arousal: 0, confidence: 0 }
        });
      });
    
    return () => {
      if (audioContextRef.current) {
        audioContextRef.current.close();
      }
    };
  }, []);
  
  useEffect(() => {
    // Subscribe to SENSOR LOOP (8-15 Hz)
    const unsubscribe = tripleLoopRuntime.subscribeSensor(() => {
      if (!analyserRef.current || !dataArrayRef.current) return;
      
      // Get frequency data
      analyserRef.current.getByteFrequencyData(dataArrayRef.current as any);
      
      // Extract features
      const { energy, pitch, tempo } = extractAudioFeatures(dataArrayRef.current);
      
      // Map to emotion
      const { valence, arousal, confidence } = audioToEmotion(energy, pitch, tempo);
      
      // Queue update (batched at 10 Hz by state throttle)
      stateThrottle.queueUpdate({
        audioEmotion: { valence, arousal, confidence }
      });
    }, 0, 'Audio FFT');
    
    return () => {
      unsubscribe();
    };
  }, []);
  
  return null;
}

// Extract audio features
function extractAudioFeatures(dataArray: Uint8Array) {
  // Energy (overall loudness)
  const energy = dataArray.reduce((sum, val) => sum + val, 0) / dataArray.length / 255;
  
  // Pitch (weighted by low vs high frequency)
  const lowFreq = dataArray.slice(0, 50).reduce((sum, val) => sum + val, 0);
  const highFreq = dataArray.slice(50, 200).reduce((sum, val) => sum + val, 0);
  const pitch = (highFreq - lowFreq) / (highFreq + lowFreq + 1);
  
  // Tempo (variance in energy over time - simplified)
  const variance = dataArray.reduce((sum, val, i, arr) => {
    if (i === 0) return 0;
    return sum + Math.abs(val - arr[i - 1]);
  }, 0) / dataArray.length;
  const tempo = Math.min(variance / 50, 1.0);
  
  return { energy, pitch, tempo };
}

// Map audio features to emotion (valence/arousal)
function audioToEmotion(energy: number, pitch: number, tempo: number) {
  // Valence: pitch + energy
  // High pitch + high energy = happy
  // Low pitch + low energy = sad
  const valence = (pitch * 0.6) + (energy * 0.4) - 0.3;
  
  // Arousal: energy + tempo
  // High energy + high tempo = excited
  // Low energy + low tempo = calm
  const arousal = (energy * 0.7) + (tempo * 0.3);
  
  // Confidence: higher when audio is present
  const confidence = Math.min(energy * 1.5, 1.0);
  
  return {
    valence: Math.max(-1, Math.min(1, valence)),
    arousal: Math.max(0, Math.min(1, arousal)),
    confidence: Math.max(0, Math.min(1, confidence))
  };
}
