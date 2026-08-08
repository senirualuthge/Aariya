// src/core/performanceIntegration.ts
/**
 * Performance Integration Module
 * 
 * Integrates all Phase 1 components:
 * - Boot Profiler
 * - Runtime Config
 * - FPS Controller
 * - Triple Loop Runtime
 * - WebSocket Client
 * - State Throttling
 */

import { runBootProfiler, type BootProfile } from './bootProfiler';
import { createRuntimeConfig, type RuntimeConfig } from './runtimeConfig';
import { fpsController, FPSMode } from './fpsController';
import { tripleLoopRuntime } from './tripleLoopRuntime';
import { wsClient } from './wsClient';
import { stateThrottle } from './stateThrottle';
import { thermalController, ThermalLevel } from './thermalController';

export interface PerformanceSystemConfig {
  wsUrl?: string;
  fpsMode?: FPSMode;
}

class PerformanceIntegration {
  private bootProfile: BootProfile | null = null;
  private runtimeConfig: RuntimeConfig | null = null;
  private initialized: boolean = false;
  
  constructor() {
    console.log('[Performance Integration] Module loaded');
  }
  
  /**
   * Initialize the entire performance system
   */
  async initialize(config: PerformanceSystemConfig = {}): Promise<void> {
    if (this.initialized) {
      console.warn('[Performance Integration] Already initialized');
      return;
    }
    
    console.log('[Performance Integration] Starting initialization...');
    
    try {
      // Step 1: Run boot profiler
      console.log('[Performance Integration] Step 1/5: Running boot profiler...');
      this.bootProfile = await runBootProfiler();
      
      // Step 2: Generate runtime config
      console.log('[Performance Integration] Step 2/5: Generating runtime config...');
      this.runtimeConfig = createRuntimeConfig(this.bootProfile.tier);
      
      // Step 3: Apply config to triple loop runtime
      console.log('[Performance Integration] Step 3/5: Configuring triple loop runtime...');
      tripleLoopRuntime.setConfig(this.runtimeConfig);
      
      // Apply config to thermal controller
      thermalController.setConfig(this.runtimeConfig);
      
      // Step 4: Initialize FPS controller
      console.log('[Performance Integration] Step 4/5: Initializing FPS controller...');
      if (config.fpsMode) {
        fpsController.setUserMode(config.fpsMode);
      }
      await fpsController.start();
      
      // Step 5: Connect WebSocket if URL provided
      if (config.wsUrl) {
        console.log('[Performance Integration] Step 5/5: Connecting WebSocket...');
        await wsClient.connect(config.wsUrl, this.runtimeConfig.wsRateHz);
      } else {
        console.log('[Performance Integration] Step 5/5: Skipping WebSocket (no URL provided)');
      }
      
      // Setup FPS controller integration with triple loop
      this.setupFPSIntegration();
      
      // Start all loops
      tripleLoopRuntime.startAll();
      
      this.initialized = true;
      console.log('[Performance Integration] ✅ Initialization complete!');
      console.log('[Performance Integration] System Status:', this.getStatus());
      
    } catch (error) {
      console.error('[Performance Integration] ❌ Initialization failed:', error);
      throw error;
    }
  }
  
  /**
   * Setup FPS controller and thermal controller to update with render loop
   */
  private setupFPSIntegration(): void {
    tripleLoopRuntime.subscribeRender((deltaTime) => {
      // Estimate GPU time (simplified - in production use FrameTimingManager)
      const frameTimeMs = deltaTime * 1000;
      const gpuMs = frameTimeMs;
      
      // Update FPS controller
      fpsController.update(deltaTime, gpuMs);
      
      // Update thermal controller
      thermalController.update(deltaTime, frameTimeMs, gpuMs);
    }, -100, 'FPS & Thermal Controller'); // High priority (negative = runs first)
  }
  
  /**
   * Get current system status
   */
  getStatus() {
    return {
      initialized: this.initialized,
      bootProfile: this.bootProfile,
      runtimeConfig: this.runtimeConfig,
      fpsController: {
        mode: fpsController.getUserMode(),
        currentTarget: fpsController.getCurrentTarget(),
        monitorHz: fpsController.getMonitorHz(),
        avgFrameTime: fpsController.getAverageFrameTime(),
        thermalThrottling: fpsController.isThermalThrottling(),
      },
      tripleLoop: tripleLoopRuntime.getStatus(),
      websocket: {
        connected: wsClient.isConnected(),
        bufferSize: wsClient.getBufferSize(),
      },
      thermal: {
        level: thermalController.getCurrentLevel(),
        throttled: thermalController.isThrottled(),
        state: thermalController.getState(),
      },
    };
  }
  
  /**
   * Shutdown the performance system
   */
  shutdown(): void {
    console.log('[Performance Integration] Shutting down...');
    
    tripleLoopRuntime.stopAll();
    wsClient.disconnect();
    
    this.initialized = false;
    console.log('[Performance Integration] Shutdown complete');
  }
  
  /**
   * Get boot profile
   */
  getBootProfile(): BootProfile | null {
    return this.bootProfile;
  }
  
  /**
   * Get runtime config
   */
  getRuntimeConfig(): RuntimeConfig | null {
    return this.runtimeConfig;
  }
  
  /**
   * Check if initialized
   */
  isInitialized(): boolean {
    return this.initialized;
  }
}

export const performanceSystem = new PerformanceIntegration();

// Export for convenience
export {
  fpsController,
  tripleLoopRuntime,
  wsClient,
  stateThrottle,
  thermalController,
  ThermalLevel,
};
