// src/core/initializePerformanceSystem.ts
/**
 * Performance System Initialization
 * 
 * Initializes all Phase 1 components in the correct order
 */

import { performanceSystem } from './performanceIntegration';
import { faceWorkerBridge } from '../systems/FaceWorkerBridge';
import { FPSMode } from './fpsController';

export interface InitOptions {
  wsUrl?: string;
  fpsMode?: FPSMode;
  enableFaceDetection?: boolean;
}

export async function initializePerformanceSystem(options: InitOptions = {}) {
  console.log('[Init] Starting performance system initialization...');
  
  try {
    // Step 1: Initialize core performance system
    await performanceSystem.initialize({
      wsUrl: options.wsUrl,
      fpsMode: options.fpsMode || FPSMode.Auto,
    });
    
    const config = performanceSystem.getRuntimeConfig();
    if (!config) {
      // Degrade gracefully — don't block the UI
      console.warn('[Init] Runtime config unavailable — running in degraded mode');
      return null;
    }
    
    // Step 2: Initialize Face Worker Bridge (if enabled)
    if (options.enableFaceDetection !== false) {
      try {
        console.log('[Init] Initializing Face Worker Bridge...');
        await faceWorkerBridge.init(config);
        faceWorkerBridge.start();
      } catch (faceErr) {
        console.warn('[Init] Face Worker Bridge failed (camera may be unavailable):', faceErr);
        // Continue without face detection
      }
    }
    
    // Step 3: Log final status
    const status = performanceSystem.getStatus();
    console.log('[Init] ✅ Performance system initialized successfully');
    console.log('[Init] System Status:', status);
    
    // Emit event for other systems
    window.dispatchEvent(new CustomEvent('performanceSystemReady', {
      detail: { status }
    }));
    
    return status;
    
  } catch (error) {
    console.error('[Init] ❌ Performance system init failed — continuing in degraded mode:', error);
    // Return null instead of throwing so the UI still mounts
    return null;
  }
}

/**
 * Shutdown performance system
 */
export function shutdownPerformanceSystem() {
  console.log('[Init] Shutting down performance system...');
  
  faceWorkerBridge.destroy();
  performanceSystem.shutdown();
  
  console.log('[Init] Performance system shut down');
}
