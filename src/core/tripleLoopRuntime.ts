// src/core/tripleLoopRuntime.ts
import type { RuntimeConfig } from './runtimeConfig';

export interface LoopSubscriber {
  fn: (deltaTime: number, now: number) => void;
  priority: number;
  name: string;
}

/**
 * Triple Loop Runtime Architecture
 * 
 * Separates concerns into three independent loops:
 * 1. Render Loop (60-120 FPS): Animation, blendshapes, gaze
 * 2. Sensor Loop (8-15 Hz): Face detection, audio FFT
 * 3. Cognition Loop (4-8 Hz): Trust, emotion, policy
 */
class TripleLoopRuntime {
  // Render loop (RAF)
  private renderSubscribers: LoopSubscriber[] = [];
  private renderRunning: boolean = false;
  private renderRafId: number | null = null;
  private lastRenderTime: number = 0;
  
  // Sensor loop (setInterval)
  private sensorSubscribers: LoopSubscriber[] = [];
  private sensorRunning: boolean = false;
  private sensorIntervalId: number | null = null;
  private lastSensorTime: number = 0;
  
  // Cognition loop (setInterval)
  private cognitionSubscribers: LoopSubscriber[] = [];
  private cognitionRunning: boolean = false;
  private cognitionIntervalId: number | null = null;
  private lastCognitionTime: number = 0;
  
  private config: RuntimeConfig | null = null;
  
  constructor() {
    console.log('[Triple Loop] Runtime initialized');
  }
  
  setConfig(config: RuntimeConfig): void {
    this.config = config;
    console.log('[Triple Loop] Config applied:', config);
    
    // Restart loops with new config if running
    if (this.sensorRunning) {
      this.stopSensorLoop();
      this.startSensorLoop();
    }
    if (this.cognitionRunning) {
      this.stopCognitionLoop();
      this.startCognitionLoop();
    }
  }
  
  // ===== RENDER LOOP (60-120 FPS) =====
  
  subscribeRender(fn: (deltaTime: number, now: number) => void, priority: number = 0, name: string = 'anonymous'): () => void {
    this.renderSubscribers.push({ fn, priority, name });
    this.renderSubscribers.sort((a, b) => a.priority - b.priority);
    console.log(`[Render Loop] Subscribed: ${name} (Priority: ${priority})`);
    return () => this.unsubscribeRender(fn);
  }
  
  unsubscribeRender(fn: (deltaTime: number, now: number) => void): void {
    this.renderSubscribers = this.renderSubscribers.filter(s => s.fn !== fn);
  }
  
  startRenderLoop(): void {
    if (this.renderRunning) return;
    this.renderRunning = true;
    this.lastRenderTime = performance.now();
    this.renderTick(this.lastRenderTime);
    console.log('[Render Loop] Started');
  }
  
  stopRenderLoop(): void {
    this.renderRunning = false;
    if (this.renderRafId !== null) {
      cancelAnimationFrame(this.renderRafId);
      this.renderRafId = null;
    }
    console.log('[Render Loop] Stopped');
  }
  
  private renderTick = (now: number): void => {
    if (!this.renderRunning) return;
    
    const deltaTime = Math.min((now - this.lastRenderTime) / 1000, 0.05);
    this.lastRenderTime = now;
    
    try {
      for (const sub of this.renderSubscribers) {
        sub.fn(deltaTime, now);
      }
    } catch (error) {
      console.error('[Render Loop] Error:', error);
    }
    
    this.renderRafId = requestAnimationFrame(this.renderTick);
  };
  
  // ===== SENSOR LOOP (8-15 Hz) =====
  
  subscribeSensor(fn: (deltaTime: number, now: number) => void, priority: number = 0, name: string = 'anonymous'): () => void {
    this.sensorSubscribers.push({ fn, priority, name });
    this.sensorSubscribers.sort((a, b) => a.priority - b.priority);
    console.log(`[Sensor Loop] Subscribed: ${name} (Priority: ${priority})`);
    return () => this.unsubscribeSensor(fn);
  }
  
  unsubscribeSensor(fn: (deltaTime: number, now: number) => void): void {
    this.sensorSubscribers = this.sensorSubscribers.filter(s => s.fn !== fn);
  }
  
  startSensorLoop(): void {
    if (this.sensorRunning) return;
    if (!this.config) {
      console.warn('[Sensor Loop] No config set, using default 10 Hz');
    }
    
    const hz = this.config?.sensorFps || 10;
    const interval = 1000 / hz;
    
    this.sensorRunning = true;
    this.lastSensorTime = performance.now();
    
    this.sensorIntervalId = window.setInterval(() => {
      const now = performance.now();
      const deltaTime = (now - this.lastSensorTime) / 1000;
      this.lastSensorTime = now;
      
      try {
        for (const sub of this.sensorSubscribers) {
          sub.fn(deltaTime, now);
        }
      } catch (error) {
        console.error('[Sensor Loop] Error:', error);
      }
    }, interval);
    
    console.log(`[Sensor Loop] Started at ${hz} Hz`);
  }
  
  stopSensorLoop(): void {
    this.sensorRunning = false;
    if (this.sensorIntervalId !== null) {
      clearInterval(this.sensorIntervalId);
      this.sensorIntervalId = null;
    }
    console.log('[Sensor Loop] Stopped');
  }
  
  // ===== COGNITION LOOP (4-8 Hz) =====
  
  subscribeCognition(fn: (deltaTime: number, now: number) => void, priority: number = 0, name: string = 'anonymous'): () => void {
    this.cognitionSubscribers.push({ fn, priority, name });
    this.cognitionSubscribers.sort((a, b) => a.priority - b.priority);
    console.log(`[Cognition Loop] Subscribed: ${name} (Priority: ${priority})`);
    return () => this.unsubscribeCognition(fn);
  }
  
  unsubscribeCognition(fn: (deltaTime: number, now: number) => void): void {
    this.cognitionSubscribers = this.cognitionSubscribers.filter(s => s.fn !== fn);
  }
  
  startCognitionLoop(): void {
    if (this.cognitionRunning) return;
    if (!this.config) {
      console.warn('[Cognition Loop] No config set, using default 6 Hz');
    }
    
    const hz = this.config?.cognitionHz || 6;
    const interval = 1000 / hz;
    
    this.cognitionRunning = true;
    this.lastCognitionTime = performance.now();
    
    this.cognitionIntervalId = window.setInterval(() => {
      const now = performance.now();
      const deltaTime = (now - this.lastCognitionTime) / 1000;
      this.lastCognitionTime = now;
      
      try {
        for (const sub of this.cognitionSubscribers) {
          sub.fn(deltaTime, now);
        }
      } catch (error) {
        console.error('[Cognition Loop] Error:', error);
      }
    }, interval);
    
    console.log(`[Cognition Loop] Started at ${hz} Hz`);
  }
  
  stopCognitionLoop(): void {
    this.cognitionRunning = false;
    if (this.cognitionIntervalId !== null) {
      clearInterval(this.cognitionIntervalId);
      this.cognitionIntervalId = null;
    }
    console.log('[Cognition Loop] Stopped');
  }
  
  // ===== LIFECYCLE =====
  
  startAll(): void {
    this.startRenderLoop();
    this.startSensorLoop();
    this.startCognitionLoop();
    console.log('[Triple Loop] All loops started');
  }
  
  stopAll(): void {
    this.stopRenderLoop();
    this.stopSensorLoop();
    this.stopCognitionLoop();
    console.log('[Triple Loop] All loops stopped');
  }
  
  getStatus() {
    return {
      render: {
        running: this.renderRunning,
        subscribers: this.renderSubscribers.length,
      },
      sensor: {
        running: this.sensorRunning,
        subscribers: this.sensorSubscribers.length,
        hz: this.config?.sensorFps || 0,
      },
      cognition: {
        running: this.cognitionRunning,
        subscribers: this.cognitionSubscribers.length,
        hz: this.config?.cognitionHz || 0,
      },
    };
  }
}

export const tripleLoopRuntime = new TripleLoopRuntime();
