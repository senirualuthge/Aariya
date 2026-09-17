export function resolveIntimacy(userSetting, memory) {
  // Hard safety check
  if (memory.safety?.dependencyRisk && memory.safety.dependencyRisk !== "low") {
      return 0; // Neutral/Calm only
  }
  
  // Cap user setting at 2 (Light Flirty) automatically for safety unless specifically overridden (not implemented yet)
  // 0 = Neutral, 1 = Friendly, 2 = Light Flirty, 3 = Soft Intimate
  return Math.min(userSetting, 2); 
}
