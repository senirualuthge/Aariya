// src/utils/backgroundPolls.js
//
// Pure schedulers for the analytics dashboard's background timers. Extracted
// from AnalyticsDashboard's hooks so the "disabled ⇒ nothing is scheduled"
// contract is unit-testable with node --test (no React renderer required).
// The hooks inject their real poll / subscribe / setInterval implementations;
// timers and subscriptions can be stubbed via the *_Impl parameters (same
// dependency-injection style as build-summary.js).

/**
 * Schedule the emotion-predictor poll loop.
 *
 * When `enabled` is false, returns `null` and schedules NOTHING — no initial
 * poll, no interval, no subscription — so a hidden / off-route mount never
 * touches /api/emotion/predictor or /api/autonomy/state.
 *
 * When enabled: subscribes first, fires `poll()` once immediately, then every
 * `pollMs` ms. Returns a cleanup that stops the timer and unsubscribes.
 *
 * @param {object} o
 * @param {boolean} o.enabled        gate — false means never schedule
 * @param {number}  [o.pollMs=15000] interval between polls
 * @param {Function} o.poll          the poll routine (fetch + state updates)
 * @param {Function} o.subscribe     () => unsubscribe function
 * @param {Function} [o.setIntervalImpl]   injectable, defaults to setInterval
 * @param {Function} [o.clearIntervalImpl] injectable, defaults to clearInterval
 * @returns {Function|null} cleanup, or null when disabled
 */
export function schedulePredictorPoll({
  enabled,
  pollMs = 15000,
  poll,
  subscribe,
  setIntervalImpl = setInterval,
  clearIntervalImpl = clearInterval,
}) {
  if (!enabled) return null;
  const unsubscribe = subscribe();
  poll();
  const timer = setIntervalImpl(poll, pollMs);
  return () => {
    clearIntervalImpl(timer);
    unsubscribe();
  };
}

/**
 * Schedule the uptime ticker — a 1s interval counting seconds since start.
 *
 * When `enabled` is false, returns `null` and schedules nothing. When
 * enabled, captures the start time via `startAt()` and calls
 * `onTick(elapsedSeconds)` once per second. Returns a cleanup that stops it.
 *
 * @param {object} o
 * @param {boolean} o.enabled  gate — false means never schedule
 * @param {Function} [o.nowImpl]  injectable clock, defaults to Date.now
 * @param {Function} o.onTick     (elapsedSeconds) => void
 * @param {Function} [o.setIntervalImpl]   injectable, defaults to setInterval
 * @param {Function} [o.clearIntervalImpl] injectable, defaults to clearInterval
 * @returns {Function|null} cleanup, or null when disabled
 */
export function startUptimeTicker({
  enabled,
  nowImpl = Date.now,
  onTick,
  setIntervalImpl = setInterval,
  clearIntervalImpl = clearInterval,
}) {
  if (!enabled) return null;
  const start = nowImpl();
  const timer = setIntervalImpl(() => {
    onTick(Math.floor((nowImpl() - start) / 1000));
  }, 1000);
  return () => clearIntervalImpl(timer);
}
