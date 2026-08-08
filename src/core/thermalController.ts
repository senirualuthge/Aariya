// src/core/thermalController.ts
/**
 * Advanced Thermal Controller (Phase 3.2)
 * 
 * Multi-tier thermal management with progressive degradation:
 * - Level 0: Normal operation
 * - Level 1: Reduce sensor FPS
 * - Level 2: Reduce blendshape LOD
 * - Level 3: Reduce render FPS
 * - Level 4: Disable face landmarks
 * 
 * Features:
 * - CPU and GPU monitoring
 * - Progressive degradation
 * - Automatic recovery
 * - Hysteresis to prevent oscillation
 */

import type { RuntimeConfig } from './runtimeConfig';
import { tripleLoopRuntime } from './tripleLoopRuntime';
import { fpsController } from './fpsController';
import { faceWorkerBridge } from '../systems/FaceWorkerBridge';

export enum ThermalLevel {
  Normal = 0,      // No throttling
  Light = 1,       // Reduce sensor FPS
  Medium = 2,      // Reduce blendshape LOD
  Heavy = 3,       // Reduce render FPS
  Critical = 4,    // Disable face landmarks
}

export interface ThermalState {
  level: ThermalLevel;
  cpuLoad: number;
  gpuFrameTime: number;
  avgFrameTime: number;
  degradationReason: string;
}

interface ThermalThresholds {
  cpuWarning: number;      // CPU usage %
  cpuCritical: number;
  gpuWarning: number;      // Frame time ms
  gpuCritical: number;
  frameTimeWarning: number;
  frameTimeCritical: number;
}

class ThermalController {
  private currentLevel: ThermalLevel = ThermalLevel.Normal;
  private originalConfig: RuntimeConfig | null = null;
  private currentConfig: RuntimeConfig | null = null;
  
  // Monitoring
  private frameTimings: number[] = [];
  private readonly FRAME_TIMING_BUFFER = 120; // 2 seconds at 60 FPS
  private cpuUsage: number = 0;
  private gpuFrameTime: number = 0;
  
  // Timers for hysteresis
  private degradeTimer: number = 0;
  private upgradeTimer: number = 0;
  
  // Thresholds
  private readonly thresholds: ThermalThresholds = {
    cpuWarning: 70,      // 70% CPU usage
    cpuCritical: 85,     // 85% CPU usage
    gpuWarning: 20,      // 20ms frame time (~50 FPS)
    gpuCritical: 30,     // 30ms frame time (~33 FPS)
    frameTimeWarning: 20,
    frameTimeCritical: 25,
  };
  
  // Timing constants
  private readonly DEGRADE_TIME_REQUIRED = 2.0;  // 2 seconds sustained
  private readonly UPGRADE_TIME_REQUIRED = 5.0;  // 5 seconds sustained
  
  constructor() {
    console.log('[Thermal Controller] Initialized');
  }
  
  /**
   * Set original runtime config (baseline)
   */
  setConfig(config: RuntimeConfig): void {
    this.originalConfig = { ...config };
    this.currentConfig = { ...config };
    console.log('[Thermal Controller] Config set:', config);
  }
  
  /**
   * Update thermal state (called every frame)
   */
  update(deltaTime: number, frameTimeMs: number, gpuMs: number): void {
    // Record frame timing
    this.recordFrameTime(frameTimeMs);
    this.gpuFrameTime = gpuMs;
    
    // Estimate CPU usage (simplified - in production use Performance API)
    this.estimateCPUUsage();
    
    // Check if we should degrade or upgrade
    const avgFrameTime = this.getAverageFrameTime();
    
    if (this.shouldDegrade(avgFrameTime, gpuMs)) {
      this.degradeTimer += deltaTime;
      this.upgradeTimer = 0;
    } else if (this.shouldUpgrade(avgFrameTime, gpuMs)) {
      this.upgradeTimer += deltaTime;
      this.degradeTimer = 0;
    } else {
      // Reset timers if in acceptable range
      this.degradeTimer = Math.max(0, this.degradeTimer - deltaTime);
      this.upgradeTimer = Math.max(0, this.upgradeTimer - deltaTime);
    }
    
    // Apply degradation if timer exceeded
    if (this.degradeTimer >= this.DEGRADE_TIME_REQUIRED) {
      this.degradePerformance(avgFrameTime, gpuMs);
      this.degradeTimer = 0;
    }
    
    // Apply upgrade if timer exceeded and not at Normal level
    if (this.upgradeTimer >= this.UPGRADE_TIME_REQUIRED && this.currentLevel > ThermalLevel.Normal) {
      this.upgradePerformance();
      this.upgradeTimer = 0;
    }
  }
  
  /**
   * Record frame time for averaging
   */
  private recordFrameTime(frameTimeMs: number): void {
    this.frameTimings.push(frameTimeMs);
    if (this.frameTimings.length > this.FRAME_TIMING_BUFFER) {
      this.frameTimings.shift();
    }
  }
  
  /**
   * Get average frame time
   */
  private getAverageFrameTime(): number {
    if (this.frameTimings.length === 0) return 0;
    const sum = this.frameTimings.reduce((a, b) => a + b, 0);
    return sum / this.frameTimings.length;
  }
  
  /**
   * Estimate CPU usage (simplified)
   */
  private estimateCPUUsage(): void {
    // In production, use Performance API or Worker to measure actual CPU
    // For now, estimate based on frame time variance
    const avgFrameTime = this.getAverageFrameTime();
    this.cpuUsage = Math.min(100, (avgFrameTime / 16.6) * 60);
  }
  
  /**
   * Check if we should degrade performance
   */
  private shouldDegrade(avgFrameTime: number, gpuMs: number): boolean {
    // Check if ANY metric exceeds warning threshold
    return (
      avgFrameTime > this.thresholds.frameTimeWarning ||
      gpuMs > this.thresholds.gpuWarning ||
      this.cpuUsage > this.thresholds.cpuWarning
    );
  }
  
  /**
   * Check if we should upgrade performance
   */
  private shouldUpgrade(avgFrameTime: number, gpuMs: number): boolean {
    // Check if ALL metrics are well below thresholds
    return (
      avgFrameTime < this.thresholds.frameTimeWarning * 0.7 &&
      gpuMs < this.thresholds.gpuWarning * 0.7 &&
      this.cpuUsage < this.thresholds.cpuWarning * 0.7
    );
  }
  
  /**
   * Degrade performance by one level
   */
  private degradePerformance(avgFrameTime: number, gpuMs: number): void {
    if (this.currentLevel >= ThermalLevel.Critical) {
      console.warn('[Thermal Controller] Already at critical level, cannot degrade further');
      return;
    }
    
    const newLevel = this.currentLevel + 1;
    const reason = this.getDegradationReason(avgFrameTime, gpuMs);
    
    console.log(`[Thermal Controller] Degrading: ${ThermalLevel[this.currentLevel]} → ${ThermalLevel[newLevel]} (${reason})`);
    
    this.currentLevel = newLevel;
    this.applyThermalLevel(newLevel, reason);
    
    // Emit event
    this.emitThermalEvent('degrade', newLevel, reason);
  }
  
  /**
   * Upgrade performance by one level
   */
  private upgradePerformance(): void {
    if (this.currentLevel <= ThermalLevel.Normal) {
      return;
    }
    
    const newLevel = this.currentLevel - 1;
    
    console.log(`[Thermal Controller] Upgrading: ${ThermalLevel[this.currentLevel]} → ${ThermalLevel[newLevel]} (recovery)`);
    
    this.currentLevel = newLevel;
    this.applyThermalLevel(newLevel, 'recovery');
    
    // Emit event
    this.emitThermalEvent('upgrade', newLevel, 'recovery');
  }
  
  /**
   * Get degradation reason based on metrics
   */
  private getDegradationReason(avgFrameTime: number, gpuMs: number): string {
    if (avgFrameTime > this.thresholds.frameTimeCritical) {
      return 'critical_frame_time';
    } else if (gpuMs > this.thresholds.gpuCritical) {
      return 'critical_gpu';
    } else if (this.cpuUsage > this.thresholds.cpuCritical) {
      return 'critical_cpu';
    } else if (avgFrameTime > this.thresholds.frameTimeWarning) {
      return 'high_frame_time';
    } else if (gpuMs > this.thresholds.gpuWarning) {
      return 'high_gpu';
    } else if (this.cpuUsage > this.thresholds.cpuWarning) {
      return 'high_cpu';
    }
    return 'sustained_load';
  }
  
  /**
   * Apply thermal level adjustments
   */
  private applyThermalLevel(level: ThermalLevel, reason: string): void {
    if (!this.originalConfig || !this.currentConfig) {
      console.warn('[Thermal Controller] No config set');
      return;
    }
    
    switch (level) {
      case ThermalLevel.Normal:
        // Restore original config
        this.currentConfig = { ...this.originalConfig };
        this.applyConfig();
        break;
        
      case ThermalLevel.Light:
        // Reduce sensor FPS (15 → 12 Hz)
        this.currentConfig.sensorFps = Math.max(8, this.originalConfig.sensorFps * 0.8);
        this.currentConfig.faceTrackingHz = Math.max(6, this.originalConfig.faceTrackingHz * 0.8);
        this.applyConfig();
        break;
        
      case ThermalLevel.Medium:
        // Keep Light adjustments + reduce blendshape LOD
        this.currentConfig.sensorFps = Math.max(8, this.originalConfig.sensorFps * 0.8);
        this.currentConfig.faceTrackingHz = Math.max(6, this.originalConfig.faceTrackingHz * 0.8);
        this.currentConfig.blendshapeCount = Math.max(12, Math.floor(this.originalConfig.blendshapeCount / 2));
        this.currentConfig.fftSize = Math.max(512, this.originalConfig.fftSize / 2);
        this.applyConfig();
        break;
        
      case ThermalLevel.Heavy:
        // Keep Medium adjustments + reduce render FPS
        this.currentConfig.sensorFps = Math.max(8, this.originalConfig.sensorFps * 0.6);
        this.currentConfig.faceTrackingHz = Math.max(6, this.originalConfig.faceTrackingHz * 0.6);
        this.currentConfig.blendshapeCount = Math.max(12, Math.floor(this.originalConfig.blendshapeCount / 2));
        this.currentConfig.fftSize = Math.max(512, this.originalConfig.fftSize / 2);
        this.currentConfig.renderFps = 30; // Force 30 FPS
        this.applyConfig();
        
        // Force FPS controller to 60 max
        fpsController.setUserMode('force60' as any);
        break;
        
      case ThermalLevel.Critical:
        // Keep Heavy adjustments + disable face landmarks
        this.currentConfig.sensorFps = 8;
        this.currentConfig.faceTrackingHz = 0; // Disable face tracking
        this.currentConfig.blendshapeCount = 12;
        this.currentConfig.fftSize = 512;
        this.currentConfig.renderFps = 30;
        this.applyConfig();
        
        // Stop face worker
        if (faceWorkerBridge.isRunning()) {
          faceWorkerBridge.stop();
        }
        break;
    }
    
    console.log('[Thermal Controller] Applied config:', this.currentConfig);
  }
  
  /**
   * Apply current config to runtime systems
   */
  private applyConfig(): void {
    if (!this.currentConfig) return;
    
    // Update triple loop runtime
    tripleLoopRuntime.setConfig(this.currentConfig);
    
    // Update face worker FPS
    if (this.currentConfig.faceTrackingHz > 0 && faceWorkerBridge.isReady()) {
      faceWorkerBridge.updateFPS(this.currentConfig.faceTrackingHz);
      if (!faceWorkerBridge.isRunning()) {
        faceWorkerBridge.start();
      }
    }
  }
  
  /**
   * Emit thermal event
   */
  private emitThermalEvent(action: 'degrade' | 'upgrade', level: ThermalLevel, reason: string): void {
    const state = this.getState();
    
    window.dispatchEvent(new CustomEvent('thermalStateChanged', {
      detail: { action, level, reason, state }
    }));
    
    console.log(`[Thermal Controller] Event: ${action} to ${ThermalLevel[level]} (${reason})`);
  }
  
  /**
   * Get current thermal state
   */
  getState(): ThermalState {
    return {
      level: this.currentLevel,
      cpuLoad: this.cpuUsage,
      gpuFrameTime: this.gpuFrameTime,
      avgFrameTime: this.getAverageFrameTime(),
      degradationReason: this.currentLevel > ThermalLevel.Normal 
        ? this.getDegradationReason(this.getAverageFrameTime(), this.gpuFrameTime)
        : 'none',
    };
  }
  
  /**
   * Get current thermal level
   */
  getCurrentLevel(): ThermalLevel {
    return this.currentLevel;
  }
  
  /**
   * Check if thermally throttled
   */
  isThrottled(): boolean {
    return this.currentLevel > ThermalLevel.Normal;
  }
  
  /**
   * Force a specific thermal level (for testing)
   */
  forceThermalLevel(level: ThermalLevel): void {
    console.log(`[Thermal Controller] Forcing level: ${ThermalLevel[level]}`);
    this.currentLevel = level;
    this.applyThermalLevel(level, 'manual_override');
  }
  
  /**
   * Reset to normal (for testing)
   */
  reset(): void {
    console.log('[Thermal Controller] Resetting to normal');
    this.currentLevel = ThermalLevel.Normal;
    this.degradeTimer = 0;
    this.upgradeTimer = 0;
    this.frameTimings = [];
    this.applyThermalLevel(ThermalLevel.Normal, 'reset');
  }
}

export const thermalController = new ThermalController();
