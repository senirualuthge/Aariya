export function mapPatternsToActions(patterns) {
  const actions = [];
  const addedTypes = new Set(); // Prevent duplicates

  const addAction = (action) => {
    if (!addedTypes.has(action.type)) {
      actions.push(action);
      addedTypes.add(action.type);
    }
  };

  patterns.forEach(p => {
    switch (p) {
      case "TRUST_DECLINE":
        addAction({ type: "REDUCE_ASSERTIVENESS", value: 0.3 });
        addAction({ type: "INCREASE_EMPATHY", value: 0.4 });
        break;

      case "EMOTIONAL_DROP":
        addAction({ type: "SWITCH_TO_COMFORT_MODE" });
        break;

      case "HIGH_CONTRADICTION":
        addAction({ type: "ENABLE_CLARIFICATION_MODE" });
        break;

      case "TRUST_BREAK_RISK":
        addAction({ type: "MAXIMIZE_SAFETY_RESPONSE" });
        break;
        
      default:
        break;
    }
  });

  return actions;
}

export function formatActionsForUI(actions) {
  return actions.map(a => {
    switch(a.type) {
      case "REDUCE_ASSERTIVENESS": return `Reduce assertiveness by ${(a.value * 100)}%`;
      case "INCREASE_EMPATHY": return `Increase empathy by ${(a.value * 100)}%`;
      case "SWITCH_TO_COMFORT_MODE": return "Switch intent to COMFORTING";
      case "ENABLE_CLARIFICATION_MODE": return "Enable Defensive / Clarification Mode";
      case "MAXIMIZE_SAFETY_RESPONSE": return "Maximize Safety Protocols & Empathy";
      default: return a.type;
    }
  });
}
