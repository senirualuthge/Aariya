/**
 * BUG #9 FIX: constructor used `self.subscribers` (window global) instead of
 * `this.subscribers`. The instance property was never set, making subscribe()
 * and start() throw TypeError on every call.
 *
 * BUG #11 FIX: the original code was a flat Set with no ordering, contradicting
 * the §5.4 priority system that prevents sensor/animation race conditions.
 * Restored the full priority-ordered subscriber map documented in §5.4.
 */

export const PRIORITIES = {
  SENSORS:        0,  // Face detection, audio FFT — always first
  EMOTION_UPDATE: 1,  // Fuse multimodal emotion
  PERSONALITY:    2,  // Adjust personality heuristics
  SOCIAL_INTENT:  3,  // Determine conversational stance
  BEHAVIOR:       4,  // Gaze, blink, idle motion
  ANIMATION:      5,  // Temporal smoothing, lip sync, pre-speech
  RENDER:         6,  // Three.js draw — always last
};

class RuntimeLoop {
  constructor() {
    // BUG #9 FIX: was `self.subscribers` — must be `this.subscribers`
    this.subscribers = {};   // priority (int) → Set<fn>
    this.raf = null;
    this.lastTime = 0;
  }

  /**
   * Subscribe a callback at a given priority level.
   * @param {number} priority  - Use PRIORITIES constants above.
   * @param {Function} fn      - Called with (deltaTime, timestamp).
   * @returns {Function} unsubscribe function.
   *
   * BUG #11 FIX: priority is now enforced; callbacks at lower numeric
   * priority always run before higher ones (SENSORS before RENDER).
   */
  subscribe(priority, fn) {
    if (!this.subscribers[priority]) {
      this.subscribers[priority] = new Set();
    }
    this.subscribers[priority].add(fn);
    // Return an unsubscribe handle
    return () => this.subscribers[priority]?.delete(fn);
  }

  start() {
    if (this.raf !== null) return; // already running

    const loop = (timestamp) => {
      const deltaTime = this.lastTime === 0
        ? 0
        : (timestamp - this.lastTime) / 1000;
      this.lastTime = timestamp;

      // BUG #11 FIX: iterate in strict priority order (0 → 6)
      const levels = Object.keys(this.subscribers)
        .map(Number)
        .sort((a, b) => a - b);

      for (const level of levels) {
        this.subscribers[level].forEach(fn => {
          try {
            fn(deltaTime, timestamp);
          } catch (err) {
            console.error(`[RuntimeLoop] Error in priority-${level} subscriber:`, err);
          }
        });
      }

      this.raf = requestAnimationFrame(loop);
    };

    this.raf = requestAnimationFrame(loop);
  }

  stop() {
    if (this.raf !== null) {
      cancelAnimationFrame(this.raf);
      this.raf = null;
      this.lastTime = 0;
    }
  }
}

export const runtime = new RuntimeLoop();