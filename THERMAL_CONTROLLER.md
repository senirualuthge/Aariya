# Advanced Thermal Controller - Documentation

## Overview

The Advanced Thermal Controller provides multi-tier thermal management with progressive degradation to maintain system stability under sustained load.

## Thermal Levels

### Level 0: Normal

- **State**: No throttling
- **Performance**: Full capability
- **Trigger**: All metrics within normal range

### Level 1: Light Throttling

- **Adjustments**:
  - Sensor FPS: 15 → 12 Hz (-20%)
  - Face tracking: 15 → 12 Hz (-20%)
- **Impact**: Minimal, imperceptible
- **Trigger**: Sustained load >2s

### Level 2: Medium Throttling

- **Adjustments**:
  - Sensor FPS: 15 → 12 Hz (-20%)
  - Face tracking: 15 → 12 Hz (-20%)
  - Blendshapes: 52 → 24 (-54%)
  - FFT size: 2048 → 1024 (-50%)
- **Impact**: Slightly reduced animation detail
- **Trigger**: Continued sustained load

### Level 3: Heavy Throttling

- **Adjustments**:
  - Sensor FPS: 15 → 9 Hz (-40%)
  - Face tracking: 15 → 9 Hz (-40%)
  - Blendshapes: 52 → 24 (-54%)
  - FFT size: 2048 → 1024 (-50%)
  - Render FPS: 120/60 → 30 (-50-75%)
- **Impact**: Noticeable performance reduction
- **Trigger**: Critical sustained load

### Level 4: Critical Throttling

- **Adjustments**:
  - Sensor FPS: 8 Hz (minimum)
  - Face tracking: **DISABLED**
  - Blendshapes: 12 (minimum)
  - FFT size: 512 (minimum)
  - Render FPS: 30 FPS
- **Impact**: Significant degradation, system survival mode
- **Trigger**: Extreme sustained load

## Thresholds

### Warning Thresholds (Level 0 → 1)

| Metric         | Threshold      |
| -------------- | -------------- |
| CPU Usage      | 70%            |
| GPU Frame Time | 20ms (~50 FPS) |
| Avg Frame Time | 20ms           |

### Critical Thresholds (Level 1+ → Higher)

| Metric         | Threshold      |
| -------------- | -------------- |
| CPU Usage      | 85%            |
| GPU Frame Time | 30ms (~33 FPS) |
| Avg Frame Time | 25ms           |

## Hysteresis

### Degradation

- **Trigger**: ANY metric exceeds threshold
- **Delay**: 2 seconds sustained
- **Action**: Degrade by 1 level

### Recovery

- **Trigger**: ALL metrics well below threshold (<70% of threshold)
- **Delay**: 5 seconds sustained
- **Action**: Upgrade by 1 level

### Purpose

Prevents rapid oscillation between levels ("thermal flapping")

## API

### Basic Usage

```typescript
import { thermalController, ThermalLevel } from "./core/thermalController";

// Get current state
const state = thermalController.getState();
console.log("Thermal level:", ThermalLevel[state.level]);
console.log("CPU load:", state.cpuLoad);
console.log("GPU frame time:", state.gpuFrameTime);

// Check if throttled
if (thermalController.isThrottled()) {
  console.log("System is thermally throttled");
}
```

### Events

```typescript
// Listen for thermal state changes
window.addEventListener("thermalStateChanged", (e) => {
  const { action, level, reason, state } = e.detail;
  console.log(`Thermal ${action}: ${ThermalLevel[level]} (${reason})`);
});
```

### Manual Control (Testing)

```typescript
// Force a specific level
thermalController.forceThermalLevel(ThermalLevel.Medium);

// Reset to normal
thermalController.reset();
```

## Monitoring

### UI Component

The `ThermalMonitor` component provides real-time visualization:

```tsx
import ThermalMonitor from "./components/ThermalMonitor";

<ThermalMonitor />;
```

**Features:**

- Real-time metrics (CPU, GPU, frame time)
- Color-coded thermal level
- Degradation reason
- Keyboard shortcut: `Ctrl+Shift+T`

### Programmatic Monitoring

```typescript
import { performanceSystem } from "./core/performanceIntegration";

const status = performanceSystem.getStatus();
console.log("Thermal state:", status.thermal);
```

## Integration

### Automatic Integration

The thermal controller is automatically integrated when you initialize the performance system:

```typescript
import { initializePerformanceSystem } from "./core/initializePerformanceSystem";

await initializePerformanceSystem();
// Thermal controller is now running
```

### Manual Integration

```typescript
import { thermalController } from "./core/thermalController";
import { tripleLoopRuntime } from "./core/tripleLoopRuntime";

// Set config
thermalController.setConfig(runtimeConfig);

// Subscribe to render loop
tripleLoopRuntime.subscribeRender(
  (deltaTime) => {
    const frameTimeMs = deltaTime * 1000;
    const gpuMs = frameTimeMs; // Or use real GPU timing

    thermalController.update(deltaTime, frameTimeMs, gpuMs);
  },
  -100,
  "Thermal Controller",
);
```

## Performance Impact

### Overhead

- **CPU**: <0.1ms per frame
- **Memory**: ~100 KB
- **Impact**: Negligible

### Benefits

- **Prevents crashes** under sustained load
- **Extends battery life** on mobile devices
- **Reduces fan noise** on laptops
- **Maintains responsiveness** even when degraded

## Example Scenarios

### Scenario 1: Gaming Laptop (Thermal Throttling)

1. **Normal**: 120 FPS, all features enabled
2. **5 minutes later**: CPU heats up
3. **Level 1**: Reduce sensor rate slightly
4. **Level 2**: Reduce animation detail
5. **Level 3**: Drop to 60 FPS
6. **Laptop cools down**: Gradual recovery back to 120 FPS

### Scenario 2: Low-End Hardware

1. **Boot**: Tier classified as MID
2. **Start**: 60 FPS with full features
3. **Face detection load**: Avg frame time increases
4. **Level 1-2**: Progressive degradation
5. **Stabilizes**: Maintains 30-60 FPS with reduced features

### Scenario 3: Meeting Mode (Multiple Users)

1. **Single user**: 60-120 FPS
2. **3 users join**: CPU load increases
3. **Level 1-3**: Progressive degradation
4. **Meeting ends**: Gradual recovery

## Best Practices

### 1. Monitor During Development

```typescript
// Log thermal events
window.addEventListener("thermalStateChanged", (e) => {
  console.log("[Thermal]", e.detail);
});
```

### 2. Test on Different Hardware

- Test on LOW, MID, HIGH tiers
- Test on laptops (thermal throttling common)
- Test on battery power

### 3. Respect Thermal State

```typescript
// Adjust AI behavior based on thermal state
if (thermalController.getCurrentLevel() >= ThermalLevel.Heavy) {
  // Reduce LLM token generation
  // Skip non-critical animations
  // Defer background tasks
}
```

### 4. Don't Fight the Controller

```typescript
// ❌ Bad: Force high settings when thermally throttled
if (thermalController.isThrottled()) {
  tripleLoopRuntime.setConfig(highPerformanceConfig); // Don't do this
}

// ✅ Good: Respect thermal state
const state = thermalController.getState();
// Controller automatically adjusts config
```

## Troubleshooting

### Thermal level too aggressive

**Symptom**: System degrades too quickly

**Solution**: Adjust thresholds in `thermalController.ts`:

```typescript
private readonly thresholds: ThermalThresholds = {
  cpuWarning: 80,      // Increase from 70
  gpuWarning: 25,      // Increase from 20
  // ...
};
```

### Thermal level not degrading

**Symptom**: System doesn't degrade under load

**Solution**: Check metrics:

```typescript
const state = thermalController.getState();
console.log("CPU:", state.cpuLoad);
console.log("GPU:", state.gpuFrameTime);
console.log("Avg frame time:", state.avgFrameTime);
```

### Rapid oscillation

**Symptom**: Level changes rapidly

**Solution**: Increase hysteresis delays:

```typescript
private readonly DEGRADE_TIME_REQUIRED = 3.0;  // Increase from 2.0
private readonly UPGRADE_TIME_REQUIRED = 7.0;  // Increase from 5.0
```

## Future Enhancements

- [ ] Platform-specific thermal APIs (Battery, CPU temp)
- [ ] Machine learning to predict thermal events
- [ ] Per-component thermal budgets
- [ ] Thermal history for analytics
- [ ] User-configurable aggressiveness

## Summary

The Advanced Thermal Controller ensures your application remains stable and responsive under any load condition while maximizing performance when possible. It intelligently degrades and recovers based on real-time metrics, providing a smooth user experience across all hardware tiers.
