// src/systems/FaceWorkerBridge.ts
/**
 * Face Worker Bridge
 * 
 * Main thread interface to the Face-api Web Worker.
 * Handles video frame capture, transfer to worker, and result interpolation.
 */

import type { RuntimeConfig } from '../core/runtimeConfig';

export interface EmotionVector {
  neutral: number;
  happy: number;
  sad: number;
  angry: number;
  fearful: number;
  disgusted: number;
  surprised: number;
}

interface EmotionResult {
  emotion: number[];
  confidence: number;
  timestamp: number;
}

class FaceWorkerBridge {
  private worker: Worker | null = null;
  private videoElement: HTMLVideoElement | null = null;
  private ready: boolean = false;
  private running: boolean = false;
  
  // Interpolation state
  private currentEmotion: EmotionVector = {
    neutral: 1,
    happy: 0,
    sad: 0,
    angry: 0,
    fearful: 0,
    disgusted: 0,
    surprised: 0,
  };
  
  private targetEmotion: EmotionVector = { ...this.currentEmotion };
  private lastUpdate: number = 0;
  private confidence: number = 0;
  
  // Callbacks
  private onEmotionCallback: ((emotion: EmotionVector, confidence: number) => void) | null = null;
  
  constructor() {
    console.log('[Face Worker Bridge] Initialized');
  }
  
  /**
   * Initialize the worker
   */
  async init(config: RuntimeConfig): Promise<void> {
    if (this.worker) {
      console.warn('[Face Worker Bridge] Already initialized');
      return;
    }
    
    return new Promise((resolve, reject) => {
      try {
        // Create worker
        this.worker = new Worker(
          new URL('./faceWorker.ts', import.meta.url),
          { type: 'module' }
        );
        
        // Setup message handler
        this.worker.onmessage = (e) => this.handleMessage(e.data);
        
        // Setup error handler
        this.worker.onerror = (error) => {
          console.error('[Face Worker Bridge] Worker error:', error);
          reject(error);
        };
        
        // Wait for READY message
        const readyHandler = (e: MessageEvent) => {
          if (e.data.type === 'READY') {
            this.ready = true;
            this.worker?.removeEventListener('message', readyHandler);
            console.log('[Face Worker Bridge] Worker ready');
            resolve();
          }
        };
        
        this.worker.addEventListener('message', readyHandler);
        
        // Initialize worker
        this.worker.postMessage({
          type: 'INIT',
          data: {
            faceTrackingHz: config.faceTrackingHz,
            modelPath: '/models', // Adjust path as needed
          },
        });
        
        // Timeout after 10 seconds
        setTimeout(() => {
          if (!this.ready) {
            reject(new Error('Worker initialization timeout'));
          }
        }, 10000);
        
      } catch (error) {
        reject(error);
      }
    });
  }
  
  /**
   * Set video element to capture frames from
   */
  setVideoElement(video: HTMLVideoElement): void {
    this.videoElement = video;
    console.log('[Face Worker Bridge] Video element set');
  }
  
  /**
   * Start face detection
   */
  start(): void {
    if (!this.ready || !this.worker) {
      console.warn('[Face Worker Bridge] Cannot start, worker not ready');
      return;
    }
    
    this.running = true;
    this.worker.postMessage({ type: 'START' });
    console.log('[Face Worker Bridge] Started');
  }
  
  /**
   * Stop face detection
   */
  stop(): void {
    if (!this.worker) return;
    
    this.running = false;
    this.worker.postMessage({ type: 'STOP' });
    console.log('[Face Worker Bridge] Stopped');
  }
  
  /**
   * Send a video frame to the worker
   * Called by sensor loop
   */
  async sendFrame(): Promise<void> {
    if (!this.running || !this.videoElement || !this.worker) return;
    
    try {
      // Create ImageBitmap from video (efficient transfer)
      const bitmap = await createImageBitmap(this.videoElement);
      
      // Transfer to worker (zero-copy)
      this.worker.postMessage(
        { type: 'FRAME', data: { bitmap } },
        [bitmap] // Transferable
      );
    } catch (error) {
      console.error('[Face Worker Bridge] Error sending frame:', error);
    }
  }
  
  /**
   * Handle messages from worker
   */
  private handleMessage(message: any): void {
    switch (message.type) {
      case 'EMOTION': {
        const result = message as EmotionResult;
        this.updateEmotion(result);
        break;
      }
      
      case 'ERROR': {
        console.error('[Face Worker Bridge] Worker error:', message.error);
        break;
      }
      
      case 'STARTED':
      case 'STOPPED':
        // Acknowledgment messages
        break;
        
      default:
        console.warn('[Face Worker Bridge] Unknown message type:', message.type);
    }
  }
  
  /**
   * Update emotion state from worker result
   */
  private updateEmotion(result: EmotionResult): void {
    const [neutral, happy, sad, angry, fearful, disgusted, surprised] = result.emotion;
    
    this.targetEmotion = {
      neutral,
      happy,
      sad,
      angry,
      fearful,
      disgusted,
      surprised,
    };
    
    this.confidence = result.confidence;
    this.lastUpdate = result.timestamp;
    
    // Trigger callback
    if (this.onEmotionCallback) {
      this.onEmotionCallback(this.targetEmotion, this.confidence);
    }
  }
  
  /**
   * Interpolate emotion for smooth animation
   * Called by render loop
   */
  interpolate(deltaTime: number): EmotionVector {
    const lerpFactor = Math.min(deltaTime * 8, 1); // Smooth interpolation
    
    for (const key in this.currentEmotion) {
      const k = key as keyof EmotionVector;
      this.currentEmotion[k] += (this.targetEmotion[k] - this.currentEmotion[k]) * lerpFactor;
    }
    
    return { ...this.currentEmotion };
  }
  
  /**
   * Get current interpolated emotion
   */
  getCurrentEmotion(): EmotionVector {
    return { ...this.currentEmotion };
  }
  
  /**
   * Get confidence of last detection
   */
  getConfidence(): number {
    return this.confidence;
  }
  
  /**
   * Register callback for emotion updates
   */
  onEmotion(callback: (emotion: EmotionVector, confidence: number) => void): void {
    this.onEmotionCallback = callback;
  }
  
  /**
   * Update FPS
   */
  updateFPS(fps: number): void {
    if (!this.worker) return;
    
    this.worker.postMessage({
      type: 'UPDATE_FPS',
      data: { fps },
    });
  }
  
  /**
   * Cleanup
   */
  destroy(): void {
    this.stop();
    
    if (this.worker) {
      this.worker.terminate();
      this.worker = null;
    }
    
    this.ready = false;
    this.running = false;
    console.log('[Face Worker Bridge] Destroyed');
  }
  
  /**
   * Check if ready
   */
  isReady(): boolean {
    return this.ready;
  }
  
  /**
   * Check if running
   */
  isRunning(): boolean {
    return this.running;
  }
}

export const faceWorkerBridge = new FaceWorkerBridge();
