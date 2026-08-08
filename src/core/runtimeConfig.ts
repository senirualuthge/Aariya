// src/core/runtimeConfig.ts
import type { PerfTier } from "./bootProfiler";

export interface RuntimeConfig {
  renderFps: number;
  sensorFps: number;
  cognitionHz: number;
  faceTrackingHz: number;
  wsRateHz: number;
  fftSize: number;
  blendshapeCount: number;
  meshLod: number;
}

export function createRuntimeConfig(tier: PerfTier): RuntimeConfig {
  switch (tier) {
    case "LOW":
      return {
        renderFps: 30,
        sensorFps: 8,
        cognitionHz: 4,
        faceTrackingHz: 6,
        wsRateHz: 6,
        fftSize: 512,
        blendshapeCount: 12,
        meshLod: 2,
      };
    case "MID":
      return {
        renderFps: 60,
        sensorFps: 12,
        cognitionHz: 6,
        faceTrackingHz: 10,
        wsRateHz: 8,
        fftSize: 1024,
        blendshapeCount: 24,
        meshLod: 1,
      };
    case "HIGH":
      return {
        renderFps: 60,
        sensorFps: 15,
        cognitionHz: 8,
        faceTrackingHz: 15,
        wsRateHz: 10,
        fftSize: 2048,
        blendshapeCount: 52,
        meshLod: 0,
      };
  }
}
