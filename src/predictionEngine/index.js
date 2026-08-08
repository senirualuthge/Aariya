export function predictNextState(signals) {
  if (!signals) return { trust: 0, mood: "Neutral", risk: "UNKNOWN" };

  const { trustTrend, emotionTrend, contradictionRate, avgTrust } = signals;

  // Simple weighted prediction formula from the docs
  let predictedTrust = avgTrust + (trustTrend * 0.8) - (contradictionRate * 0.3);

  let risk = "LOW";
  if (predictedTrust < 0.4) risk = "HIGH";
  else if (predictedTrust < 0.7) risk = "MEDIUM";

  let mood = "Neutral";
  if (emotionTrend > 0.1) mood = "Improving";
  else if (emotionTrend < -0.1) mood = "Declining";

  return {
    trust: predictedTrust.toFixed(2),
    mood,
    risk
  };
}
