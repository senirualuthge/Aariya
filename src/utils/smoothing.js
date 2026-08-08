export function ema(current, previous, alpha = 0.3) {
  if (previous === undefined || previous === null) return current;
  return alpha * current + (1 - alpha) * previous;
}
