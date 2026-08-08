import { ema } from '../utils/smoothing';

export function extractSignals(sessions, prevSignals = null) {
  if (!sessions || sessions.length === 0) {
    return { avgTrust: 0, trustTrend: 0, avgEmotion: 0, emotionTrend: 0, contradictionRate: 0 };
  }

  const last5 = sessions.slice(-5);

  // Map database fields:
  // We use `psi` (Personality Satisfaction Index) as a proxy for Trust
  // We use `ecs` (Emotional Continuity Score) as a proxy for Emotion
  const trusts = last5.map(s => s.psi || 0);
  const emotions = last5.map(s => s.ecs ? (s.ecs / 100) : 0); // Assuming ECS is 0-100, normalize to 0-1
  const contradictions = last5.map(s => s.contradiction || 0);

  const currentAvgTrust = avg(trusts);
  const currentEmotion = avg(emotions);
  
  let rawTrustTrend = trend(trusts);
  let rawEmotionTrend = trend(emotions);
  
  const contradictionRate = avg(contradictions);

  // Apply EMA smoothing if previous signals exist
  const trustTrend = prevSignals ? ema(rawTrustTrend, prevSignals.trustTrend) : rawTrustTrend;
  const emotionTrend = prevSignals ? ema(rawEmotionTrend, prevSignals.emotionTrend) : rawEmotionTrend;

  return {
    avgTrust: currentAvgTrust,
    trustTrend,
    avgEmotion: currentEmotion,
    emotionTrend,
    contradictionRate
  };
}

function avg(arr) {
  if (!arr.length) return 0;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

function trend(arr) {
  if (arr.length < 2) return 0;
  return arr[arr.length - 1] - arr[0]; // simple slope
}
