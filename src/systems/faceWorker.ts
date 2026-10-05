// src/systems/faceWorker.ts
/**
 * Face-api Web Worker
 * 
 * Runs face detection and emotion recognition off the main thread
 * using OffscreenCanvas for video frame transfer.
 * 
 * Outputs compressed emotion vectors (no raw landmarks) and, when the
 * face-recognition model is available, a 128-d identity descriptor per face.
 */

import * as faceapi from 'face-api.js';

interface WorkerConfig {
  faceTrackingHz: number;
  modelPath: string;
}

interface EmotionResult {
  type: 'EMOTION';
  emotion: number[]; // [neutral, happy, sad, angry, fearful, disgusted, surprised]
  confidence: number;
  timestamp: number;
}

interface IdentityResult {
  type: 'IDENTITY';
  descriptor: number[]; // 128-d face-api descriptor
  confidence: number;
  timestamp: number;
}

let running = false;
let fps = 10;
let modelsLoaded = false;
let lastProcessTime = 0;

// Identity is optional: face-api ships the recognition weights as a separate
// download. When they are absent we still detect and read emotion, we just
// cannot tell *who* the face belongs to — so this degrades instead of throwing.
let recognitionReady = false;

/**
 * Initialize face-api models
 */
async function initModels(modelPath: string): Promise<void> {
  if (modelsLoaded) return;
  
  try {
    console.log('[Face Worker] Loading models from:', modelPath);
    
    // Load TinyFaceDetector (lightweight, fast)
    await faceapi.nets.tinyFaceDetector.loadFromUri(modelPath);
    
    // Load FaceExpressionNet for emotion detection
    await faceapi.nets.faceExpressionNet.loadFromUri(modelPath);
    
    modelsLoaded = true;
    console.log('[Face Worker] Models loaded successfully');
  } catch (error) {
    console.error('[Face Worker] Failed to load models:', error);
    throw error;
  }
}

/**
 * Load the recognition net for person identification.
 *
 * Separated from initModels on purpose: a missing
 * face_recognition_model-weights_manifest.json must not take down emotion
 * detection. Failure is reported once via an IDENTITY_UNAVAILABLE message so
 * the UI can say "identity off" instead of silently never matching anyone.
 */
async function initIdentityModels(modelPath: string): Promise<void> {
  if (recognitionReady) return;
  try {
    await faceapi.nets.faceLandmark68Net.loadFromUri(modelPath);
    await faceapi.nets.faceRecognitionNet.loadFromUri(modelPath);
    recognitionReady = true;
    console.log('[Face Worker] Identity models loaded');
  } catch (error) {
    recognitionReady = false;
    console.warn(
      '[Face Worker] Identity unavailable — drop face_recognition_model-weights_manifest.json ' +
      'and face_recognition_model-shard1 into public/models to enable person identification.',
      error,
    );
    self.postMessage({
      type: 'IDENTITY_UNAVAILABLE',
      error: 'face_recognition_model weights not found',
    });
  }
}

/**
 * Process a video frame and extract emotion
 */
async function processFrame(bitmap: ImageBitmap): Promise<EmotionResult | null> {
  try {
    const now = performance.now();
    const minInterval = 1000 / fps;

    // Throttle processing to target FPS
    if (now - lastProcessTime < minInterval) {
      bitmap.close();
      return null;
    }

    lastProcessTime = now;

    // Detect the face once, then chain the extra stages onto that result so we
    // never pay for a second detector pass.
    let detection = await faceapi
      .detectSingleFace(bitmap, new faceapi.TinyFaceDetectorOptions({
        inputSize: 224, // Smaller = faster
        scoreThreshold: 0.5
      }))
      .withFaceExpressions();

    if (!detection) {
      bitmap.close();
      return null;
    }

    // Person identification needs landmarks + the recognition net. Chained onto
    // the existing detection, and skipped entirely when the weights are absent.
    let identity: IdentityResult | null = null;
    if (recognitionReady) {
      try {
        const identified = await detection.withFaceLandmarks().withFaceDescriptor();
        if (identified?.descriptor) {
          identity = {
            type: 'IDENTITY',
            descriptor: Array.from(identified.descriptor),
            confidence: identified.detection.score,
            timestamp: now,
          };
        }
      } catch (error) {
        console.warn('[Face Worker] Descriptor extraction failed:', error);
      }
    }

    // Close bitmap to free memory
    bitmap.close();

    if (identity) {
      self.postMessage(identity);
    }

    if (!detection.expressions) {
      return null;
    }

    // Extract emotion vector (7 values)
    const expr = detection.expressions;
    const emotion = [
      expr.neutral,
      expr.happy,
      expr.sad,
      expr.angry,
      expr.fearful,
      expr.disgusted,
      expr.surprised,
    ];

    // Quantize to 8-bit for compression (optional)
    const quantized = emotion.map(v => Math.round(v * 255) / 255);

    return {
      type: 'EMOTION',
      emotion: quantized,
      confidence: detection.detection.score,
      timestamp: now,
    };
  } catch (error) {
    console.error('[Face Worker] Error processing frame:', error);
    bitmap.close();
    return null;
  }
}

/**
 * Message handler
 */
self.onmessage = async (e: MessageEvent) => {
  const { type, data } = e.data;
  
  try {
    switch (type) {
      case 'INIT': {
        const config = data as WorkerConfig;
        fps = config.faceTrackingHz;
        
        await initModels(config.modelPath);
        await initIdentityModels(config.modelPath);

        self.postMessage({ type: 'READY' });
        console.log(`[Face Worker] Initialized at ${fps} Hz`);
        break;
      }
      
      case 'START': {
        running = true;
        console.log('[Face Worker] Started');
        self.postMessage({ type: 'STARTED' });
        break;
      }
      
      case 'STOP': {
        running = false;
        console.log('[Face Worker] Stopped');
        self.postMessage({ type: 'STOPPED' });
        break;
      }
      
      case 'FRAME': {
        if (!running || !modelsLoaded) {
          if (data.bitmap) {
            data.bitmap.close();
          }
          return;
        }
        
        const result = await processFrame(data.bitmap);
        
        if (result) {
          self.postMessage(result);
        }
        break;
      }
      
      case 'UPDATE_FPS': {
        fps = data.fps;
        console.log(`[Face Worker] FPS updated to ${fps}`);
        break;
      }
      
      default:
        console.warn('[Face Worker] Unknown message type:', type);
    }
  } catch (error) {
    console.error('[Face Worker] Error handling message:', error);
    self.postMessage({ 
      type: 'ERROR', 
      error: error instanceof Error ? error.message : 'Unknown error' 
    });
  }
};

// Handle errors
self.onerror = (error) => {
  console.error('[Face Worker] Unhandled error:', error);
  self.postMessage({ type: 'ERROR', error: error.message });
};

console.log('[Face Worker] Worker script loaded');
