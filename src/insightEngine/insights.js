export function generateInsightsFromPatterns(patterns) {
  const insights = [];

  patterns.forEach(p => {
    switch (p) {
      case "TRUST_DECLINE":
        insights.push("User trust is dropping steadily due to recent interactions");
        break;

      case "EMOTIONAL_DROP":
        insights.push("User's emotional state has been declining recently");
        break;

      case "HIGH_CONTRADICTION":
        insights.push("High frequency of contradictions detected in recent turns");
        break;

      case "TRUST_BREAK_RISK":
        insights.push("CRITICAL: High risk of user disengagement due to cumulative instability");
        break;
      
      default:
        break;
    }
  });

  return insights;
}
