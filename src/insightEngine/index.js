import { extractSignals } from "./signals";
import { detectPatterns } from "./patterns";
import { generateInsightsFromPatterns } from "./insights";

export function generateInsights(sessions, prevSignals = null, thresholds = null) {
  const signals = extractSignals(sessions, prevSignals);
  const patterns = detectPatterns(signals, thresholds);
  const insights = generateInsightsFromPatterns(patterns);

  return { signals, patterns, insights };
}
