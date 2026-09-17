# Performance System - Phase 1 Implementation

## Overview

This directory contains the Phase 1 implementation of the AI Girl performance optimization system. It provides adaptive performance management with hardware-aware configuration, 120 FPS support, and efficient resource utilization.

## Components

### 1. Boot Profiler (`bootProfiler.ts`)

- **Purpose**: Detect hardware capabilities and classify into performance tiers
- **Features**:
  - CPU benchmark (50ms test)
  - GPU benchmark (60 frame test)
  - Memory detection
  - Core count detection
- **Tiers**: LOW, MID, HIGH

### 2. Runtime Config (`runtimeConfig.ts`)

- **Purpose**: Generate tier-specific performance configurations
- **Configurations**:
  - Render FPS (30/60/60-120)
  - Sensor FPS (8/12/15)
  - Cognition Hz (4/6/8)
  - Face tracking Hz (6/10/15)
  - WebSocket rate Hz (6/8/10)
  - FFT size (512/1024/2048)
  - Blendshape count (12/24/52)
  - Mesh LOD (2/1/0)

### 3. FPS Controller (`fpsController.ts`)

- **Purpose**: Adaptive 120 FPS support with dynamic switching
- **Features**:
  - Monitor capability detection
  - Performance testing (120 FPS headroom check)
  - Dynamic runtime switching (60 ↔ 120)
  - GPU-based decisions with hysteresis timers
  - Thermal throttling protection
  - Battery mode detection
  - VRR (G-Sync/FreeSync) optimization
  - Background/unfocused handling
  - User settings (Auto/Force60/Force120)

### 4. Triple Loop Runtime (`tripleLoopRuntime.ts`)

- **Purpose**: Separate concerns into three independent loops
- **Loops**:
  1. **Render Loop** (60-120 FPS, RAF): Animation, blendshapes, gaze
  2. **Sensor Loop** (8-15 Hz, setInterval): Face detection, audio FFT
  3. **Cognition Loop** (4-8 Hz, setInterval): Trust, emotion, policy
- **Benefits**:
  - No main thread blocking
  - Predictable performance budgets
  - Independent scaling

### 5. WebSocket Client (`wsClient.ts`)

- **Purpose**: Efficient network communication with msgpack encoding
- **Features**:
  - Message batching at configurable rate (default 10 Hz)
  - msgpack encoding (~40% less CPU vs JSON)
  - Automatic reconnection with exponential backoff
  - Event-driven message handling
  - Type-safe message routing

### 6. State Throttle (`stateThrottle.ts`)

- **Purpose**: Prevent excessive React re-renders
- **Features**:
  - Batches Zustand state updates at 10 Hz
  - Supports multiple stores
  - Force commit option for critical updates
  - Configurable commit rate

### 7. Performance Integration (`performanceIntegration.ts`)

- **Purpose**: Orchestrate all components into unified system
- **Features**:
  - One-line initialization
  - Automatic configuration
  - Status monitoring
  - Graceful shutdown

## Usage

### Quick Start

```typescript
import { performanceSystem } from "./core/performanceIntegration";

// Initialize the entire performance system
await performanceSystem.initialize({
  wsUrl: "ws://localhost:8000/ws",
  fpsMode: FPSMode.Auto, // or Force60, Force120
});

// Check status
console.log(performanceSystem.getStatus());
```

### Using Individual Components

#### FPS Controller

```typescript
import { fpsController, FPSMode } from "./core/fpsController";

// Start FPS controller
await fpsController.start();

// Change user mode
fpsController.setUserMode(FPSMode.Force120);

// Get current target
const currentFPS = fpsController.getCurrentTarget(); // 60 or 120

// Check thermal throttling
if (fpsController.isThermalThrottling()) {
  console.log("System is thermal throttling");
}
```

#### Triple Loop Runtime

```typescript
import { tripleLoopRuntime } from "./core/tripleLoopRuntime";

// Subscribe to render loop (60-120 FPS)
tripleLoopRuntime.subscribeRender(
  (deltaTime, now) => {
    // Update animations, blendshapes
  },
  0,
  "Animation System",
);

// Subscribe to sensor loop (8-15 Hz)
tripleLoopRuntime.subscribeSensor(
  (deltaTime, now) => {
    // Trigger face detection, audio FFT
  },
  0,
  "Sensor System",
);

// Subscribe to cognition loop (4-8 Hz)
tripleLoopRuntime.subscribeCognition(
  (deltaTime, now) => {
    // Update trust, emotion, policy
  },
  0,
  "Cognition System",
);

// Start all loops
tripleLoopRuntime.startAll();
```

#### WebSocket Client

```typescript
import { wsClient } from './core/wsClient';

// Connect
await wsClient.connect('ws://localhost:8000/ws', 10); // 10 Hz batching

// Queue messages (batched)
wsClient.queue({ type: 'emotion', value: [0.7, 0.1, ...] });
wsClient.queue({ type: 'trust_delta', value: 0.01 });

// Send immediately (bypass batching)
wsClient.sendImmediate({ type: 'urgent', data: 'critical' });

// Register message handler
wsClient.on('response', (data) => {
  console.log('Received:', data);
});
```

#### State Throttle

```typescript
import { stateThrottle } from "./core/stateThrottle";
import { useStore } from "./store";

// Register Zustand store
stateThrottle.registerStore(useStore.setState);

// Queue updates (batched at 10 Hz)
stateThrottle.queueUpdate({ trust: 0.65 });
stateThrottle.queueUpdate({ mood: "happy" });

// Force immediate commit
stateThrottle.forceCommit();
```

## Performance Targets

### Client Frame Budget (16.6ms at 60 FPS, 8.3ms at 120 FPS)

| Component            | Budget @ 60 FPS | Budget @ 120 FPS |
| -------------------- | --------------- | ---------------- |
| Three.js render      | 4-6ms           | 3-4ms            |
| Animation solve      | 1ms             | 0.5ms            |
| State read           | <0.5ms          | <0.3ms           |
| Sensor interpolation | <0.5ms          | <0.3ms           |
| Idle buffer          | 8ms             | 3ms              |

### Network

| Channel         | Rate              |
| --------------- | ----------------- |
| Client → Server | 5-10 Hz (batched) |
| Server → Client | Event-driven      |

### Success Metrics

- ✅ Stable 60 FPS on MID tier
- ✅ Stable 120 FPS on HIGH tier with <8ms GPU time
- ✅ No main thread blocking
- ✅ <700ms perceived response latency
- ✅ Graceful degradation under load
- ✅ No oscillation between 60↔120 FPS

## Events

The system emits several custom events:

```typescript
// FPS target changed
window.addEventListener("fpsTargetChanged", (e) => {
  console.log("FPS target:", e.detail.fps);
});

// FPS changed with reason
window.addEventListener("fpsChanged", (e) => {
  console.log("FPS changed:", e.detail);
  // { from: 60, to: 120, reason: 'performance_upgrade', metric: 6.8 }
});

// WebSocket message received
window.addEventListener("wsMessage", (e) => {
  console.log("WS message:", e.detail);
});
```

## Monitoring

```typescript
// Get comprehensive system status
const status = performanceSystem.getStatus();

console.log(status);
/*
{
  initialized: true,
  bootProfile: { tier: 'HIGH', cpuScore: 45000, ... },
  runtimeConfig: { renderFps: 60, sensorFps: 15, ... },
  fpsController: {
    mode: 'auto',
    currentTarget: 120,
    monitorHz: 144,
    avgFrameTime: 7.2,
    thermalThrottling: false
  },
  tripleLoop: {
    render: { running: true, subscribers: 5 },
    sensor: { running: true, subscribers: 3, hz: 15 },
    cognition: { running: true, subscribers: 4, hz: 8 }
  },
  websocket: {
    connected: true,
    bufferSize: 0
  }
}
*/
```

## Troubleshooting

### FPS stuck at 60 on 120Hz monitor

1. Check user mode: `fpsController.getUserMode()`
2. Check monitor detection: `fpsController.getMonitorHz()`
3. Run performance test manually
4. Check thermal throttling: `fpsController.isThermalThrottling()`

### High frame times

1. Check average frame time: `fpsController.getAverageFrameTime()`
2. Review frame timing graph: `fpsController.getFrameTimings()`
3. Check loop subscriber counts: `tripleLoopRuntime.getStatus()`
4. Verify sensor loop not running on main thread

### WebSocket not connecting

1. Check connection status: `wsClient.isConnected()`
2. Verify URL is correct
3. Check server is running
4. Review browser console for errors

## Next Steps

- [ ] Implement Face-api Web Worker (Phase 1.3)
- [ ] Migrate existing systems to triple loop
- [ ] Add performance telemetry
- [ ] Create debug UI for monitoring
- [ ] Implement Phase 2 (Backend optimization)

## Dependencies

- `@msgpack/msgpack` - Binary serialization for WebSocket
- `zustand` - State management
- `react` - UI framework

## License

Part of the AI Girl project.
