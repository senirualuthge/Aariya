# Phase 1 Migration Guide

## Overview

This guide explains how to migrate existing systems to the new triple loop architecture.

## Migration Status

### ✅ Completed

- Boot profiler and hardware tier detection
- Runtime configuration
- Adaptive FPS controller (60-120 FPS)
- Triple loop runtime architecture
- WebSocket client with msgpack
- State throttling system
- Face-api Web Worker
- Face Worker Bridge
- Triple Loop Adapter
- Audio FFT System migration

### 🔄 In Progress

- Migrating remaining systems to triple loop
- Removing old EmotionRecognitionSystem (replaced by Face Worker)

### ⏳ Pending

- Backend msgpack support
- Redis streams integration
- Performance telemetry

## Architecture Changes

### Old Architecture (Single Loop)

```
RAF (60 FPS) → All Systems
  ├─ Face Detection (12-25ms) ❌ BLOCKS
  ├─ Audio FFT
  ├─ Emotion Updates
  ├─ Trust Calculation
  ├─ Animation
  └─ Rendering
```

### New Architecture (Triple Loop)

```
Render Loop (60-120 FPS, RAF)
  ├─ Blendshape Interpolation
  ├─ Gaze Updates
  └─ Idle Animation

Sensor Loop (8-15 Hz, setInterval)
  ├─ Face Worker Trigger ✅ OFF MAIN THREAD
  └─ Audio FFT

Cognition Loop (4-8 Hz, setInterval)
  ├─ Trust Updates
  ├─ Emotion Fusion
  ├─ Policy Gating
  └─ WebSocket Batching
```

## System Migration

### Face Detection System

**Old:** `EmotionRecognitionSystem.jsx`

- Ran face-api on main thread
- Blocked render loop for 12-25ms
- Updated Zustand per frame

**New:** `FaceWorkerBridge.ts` + `faceWorker.ts`

- Runs face-api in Web Worker
- Main thread never blocks
- Emotion interpolation in render loop
- State updates throttled to 10 Hz

**Migration:**

```tsx
// OLD - Remove this
import EmotionRecognitionSystem from "./systems/EmotionRecognitionSystem";
<EmotionRecognitionSystem />;

// NEW - Already included in TripleLoopAdapter
import { TripleLoopAdapter } from "./systems/TripleLoopAdapter";
<TripleLoopAdapter />;
```

### Audio System

**Old:** `AudioEmotionSystem.jsx`

- Subscribed to old runtime loop
- Updated Zustand directly

**New:** `AudioFFTSystem.tsx`

- Subscribes to Sensor Loop (8-15 Hz)
- Uses state throttling

**Migration:**

```tsx
// OLD - Remove this
import AudioEmotionSystem from "./systems/AudioEmotionSystem";
<AudioEmotionSystem />;

// NEW - Use migrated version
import AudioFFTSystem from "./systems/AudioFFTSystem";
<AudioFFTSystem />;
```

### Animation Systems

**Status:** Compatible with both old and new runtime

**Migration:** No changes needed yet. These will be migrated in Phase 3.

## How to Migrate a System

### 1. Identify Loop Type

Determine which loop your system belongs to:

- **Render Loop (60-120 FPS):** Animation, blendshapes, gaze, visual effects
- **Sensor Loop (8-15 Hz):** Input sampling, face detection, audio FFT
- **Cognition Loop (4-8 Hz):** AI logic, trust, emotion, policy

### 2. Subscribe to Appropriate Loop

```tsx
import { tripleLoopRuntime } from "../core/tripleLoopRuntime";

// Render loop
tripleLoopRuntime.subscribeRender(
  (deltaTime, now) => {
    // Update animations
  },
  priority,
  "SystemName",
);

// Sensor loop
tripleLoopRuntime.subscribeSensor(
  (deltaTime, now) => {
    // Sample inputs
  },
  priority,
  "SystemName",
);

// Cognition loop
tripleLoopRuntime.subscribeCognition(
  (deltaTime, now) => {
    // Update AI state
  },
  priority,
  "SystemName",
);
```

### 3. Use State Throttling

```tsx
import { stateThrottle } from "../core/stateThrottle";

// Queue updates (batched at 10 Hz)
stateThrottle.queueUpdate({
  trust: 0.65,
  mood: "happy",
});

// Force immediate commit (rare)
stateThrottle.forceCommit();
```

### 4. Use Refs for Per-Frame Data

```tsx
// DON'T update Zustand per frame
useStore.setState({ blendshapes: newValues }); // ❌

// DO use refs for per-frame data
const blendshapesRef = useRef(newValues); // ✅
```

## Testing

### Check FPS

```tsx
import { fpsController } from "./core/fpsController";

console.log("Current FPS:", fpsController.getCurrentTarget());
console.log("Avg frame time:", fpsController.getAverageFrameTime());
```

### Check Loop Status

```tsx
import { tripleLoopRuntime } from "./core/tripleLoopRuntime";

console.log("Loop status:", tripleLoopRuntime.getStatus());
```

### Check Face Worker

```tsx
import { faceWorkerBridge } from "./systems/FaceWorkerBridge";

console.log("Face worker ready:", faceWorkerBridge.isReady());
console.log("Face worker running:", faceWorkerBridge.isRunning());
console.log("Current emotion:", faceWorkerBridge.getCurrentEmotion());
```

## Performance Targets

| Metric             | Old         | New    | Target     |
| ------------------ | ----------- | ------ | ---------- |
| Main thread budget | 25-40ms     | 8-10ms | <16.6ms    |
| Face detection     | Main thread | Worker | Off thread |
| Zustand writes     | 60/sec      | 10/sec | ≤10/sec    |
| Network rate       | 60/sec      | 10/sec | 5-10/sec   |
| Render FPS (MID)   | 30-45       | 60     | 60         |
| Render FPS (HIGH)  | 45-60       | 60-120 | 60-120     |

## Troubleshooting

### Face detection not working

1. Check worker is ready: `faceWorkerBridge.isReady()`
2. Check video element is set
3. Check models are loaded in `/public/models`
4. Check browser console for worker errors

### FPS not improving

1. Check current target: `fpsController.getCurrentTarget()`
2. Check frame timings: `fpsController.getFrameTimings()`
3. Verify systems are migrated to correct loops
4. Check for main thread blocking

### State not updating

1. Check state throttle is registered
2. Verify `queueUpdate` is being called
3. Check commit is scheduled: `stateThrottle.isCommitScheduled()`
4. Force commit to test: `stateThrottle.forceCommit()`

## Next Steps

1. ✅ Remove old `EmotionRecognitionSystem.jsx`
2. ✅ Remove old `AudioEmotionSystem.jsx`
3. ⏳ Migrate animation systems to render loop
4. ⏳ Migrate AI logic to cognition loop
5. ⏳ Add performance telemetry
6. ⏳ Implement Phase 2 (Backend optimization)
