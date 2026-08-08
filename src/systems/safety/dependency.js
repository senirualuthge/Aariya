export function checkDependency(userText, memory) {
  const riskyPhrases = [
    "only you",
    "need you",
    "don't need anyone else",
    "you're all i have"
  ];

  const lowerText = userText.toLowerCase();

  if (riskyPhrases.some(p => lowerText.includes(p))) {
    memory.safety.dependencyRisk = "medium";
    memory.emotional.seeksReassurance = true;
    console.warn("Safety Trigger: Dependency risk detected");
  }

  if (memory.safety.romanticAttempts > 3) {
    memory.safety.dependencyRisk = "high";
  }

  return memory;
}
