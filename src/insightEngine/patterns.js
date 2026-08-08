export function detectPatterns(signals, thresholds) {
  const patterns = [];

  // Use adaptive thresholds if available, fallback to defaults
  const trustDropThresh = thresholds?.trustDrop ?? -0.2;
  const emotionDropThresh = thresholds?.emotionDrop ?? -0.2;
  const contradictionHighThresh = thresholds?.contradictionHigh ?? 0.5;

  if (signals.trustTrend < trustDropThresh) {
    patterns.push("TRUST_DECLINE");
  }

  if (signals.emotionTrend < emotionDropThresh) {
    patterns.push("EMOTIONAL_DROP");
  }

  if (signals.contradictionRate > contradictionHighThresh) {
    patterns.push("HIGH_CONTRADICTION");
  }

  if (signals.avgTrust < 0.4 && signals.contradictionRate > 0.4) {
    patterns.push("TRUST_BREAK_RISK");
  }

  return patterns;
}
