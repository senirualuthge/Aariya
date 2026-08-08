// src/systems/TripleLoopAdapter.tsx

declare global {
  interface Window {
    emotionRef?: React.MutableRefObject<{
      neutral: number;
      happy: number;
      sad: number;
      angry: number;
      fearful: number;
      disgusted: number;
      surprised: number;
    } | null>;
  }
}
/**
 * Triple Loop Adapter
 * 
 * Migrates existing systems to the new triple loop architecture.
 * Provides compatibility layer while systems are being refactored.
 */

import React, { useEffect } from 'react';
import { tripleLoopRuntime } from '../core/tripleLoopRuntime';
import { faceWorkerBridge } from './FaceWorkerBridge';
import { stateThrottle } from '../core/stateThrottle';
import useStore from '../store';

export function TripleLoopAdapter() {
  const videoRef = useStore(state => state.videoRef);
  const tracking = useStore(state => state.tracking);
  
  useEffect(() => {
    console.log('[Triple Loop Adapter] Initializing...');
    
    // Setup Face Worker Bridge with video element
    if (videoRef?.current && tracking) {
      faceWorkerBridge.setVideoElement(videoRef.current);
    }
    
    // Register Zustand store with state throttle
    stateThrottle.registerStore(useStore.setState);
    
    // === RENDER LOOP SUBSCRIBERS (60-120 FPS) ===
    
    // 1. Animation interpolation
    const unsubRenderAnimation = tripleLoopRuntime.subscribeRender((deltaTime) => {
      // Interpolate face emotion for smooth animation
      if (faceWorkerBridge.isRunning()) {
        const emotion = faceWorkerBridge.interpolate(deltaTime);
        
        // Update refs (not store) for per-frame data
        if (window.emotionRef) {
            window.emotionRef.current = emotion;
        }
      }
    }, 10, 'Emotion Interpolation');
    
    // 2. Blendshape updates (would go here)
    // 3. Gaze updates (would go here)
    // 4. Idle animation (would go here)
    
    // === SENSOR LOOP SUBSCRIBERS (8-15 Hz) ===
    
    // 1. Face detection trigger
    const unsubSensorFace = tripleLoopRuntime.subscribeSensor(async () => {
      if (faceWorkerBridge.isRunning()) {
        await faceWorkerBridge.sendFrame();
      }
    }, 0, 'Face Detection Trigger');
    
    // 2. Audio FFT (existing AudioEmotionSystem can stay as-is)
    
    // === COGNITION LOOP SUBSCRIBERS (4-8 Hz) ===
    
    // 1. Emotion state updates (throttled)
    faceWorkerBridge.onEmotion((emotion, confidence) => {
      // Map to valence/arousal
      const { valence, arousal } = emotionToValenceArousal(emotion);
      
      // Queue update (batched at 10 Hz)
      stateThrottle.queueUpdate({
        userEmotion: {
          primary: getDominantEmotion(emotion),
          valence,
          arousal,
        },
        faceDetected: confidence > 0.5,
        faceLastSeen: Date.now(),
      });
    });
    
    // 2. Trust updates (would go here)
    // 3. Contradiction scoring (would go here)
    // 4. Policy gating (would go here)
    
    console.log('[Triple Loop Adapter] Initialized');
    
    return () => {
      unsubRenderAnimation();
      unsubSensorFace();
      stateThrottle.unregisterStore(useStore.setState);
      console.log('[Triple Loop Adapter] Cleaned up');
    };
  }, [videoRef, tracking]);
  
  return null;
}

/**
 * Convert emotion vector to valence/arousal
 */
function emotionToValenceArousal(emotion: {
  neutral: number;
  happy: number;
  sad: number;
  angry: number;
  fearful: number;
  disgusted: number;
  surprised: number;
}): { valence: number; arousal: number } {
  // Weighted mapping
  const valence = 
    emotion.happy * 0.8 +
    emotion.surprised * 0.2 +
    emotion.sad * -0.6 +
    emotion.angry * -0.7 +
    emotion.fearful * -0.5 +
    emotion.disgusted * -0.8;
  
  const arousal =
    emotion.happy * 0.6 +
    emotion.angry * 0.8 +
    emotion.surprised * 0.8 +
    emotion.fearful * 0.9 +
    emotion.disgusted * 0.5 +
    emotion.sad * -0.4;
  
  return {
    valence: Math.max(-1, Math.min(1, valence)),
    arousal: Math.max(-1, Math.min(1, arousal)),
  };
}

/**
 * Get dominant emotion from vector
 */
function getDominantEmotion(emotion: {
  neutral: number;
  happy: number;
  sad: number;
  angry: number;
  fearful: number;
  disgusted: number;
  surprised: number;
}): string {
  let maxEmotion = 'neutral';
  let maxVal = emotion.neutral;
  
  for (const [key, val] of Object.entries(emotion)) {
    if (val > maxVal) {
      maxVal = val;
      maxEmotion = key;
    }
  }
  
  return maxEmotion;
}
