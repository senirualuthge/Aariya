export function getFlirtMode(memory) {
    const risk = memory.safety.dependencyRisk;
    // Handle both new schema ("context.mood") and potentially legacy locations if needed
    const mood = memory.context?.mood || "neutral";

    // HARD STOP
    // If dependency risk is high, revert to strict Aariya (calm/grounded)
    if (risk === "high") {
        return "aariyaPersonality"; 
    }

    // Medium risk → playful only, no deep flirting
    if (risk === "medium") {
        return "extraExcited"; // acts as "playful/bubbly" but not deeply intimate
    }

    // Low risk → allow flirt based on mood
    if (mood === "shy") return "shyFlirty";
    if (mood === "flirty") return "flirtyMode"; // Ensure mood matches detecting string
    if (mood === "playful") return "extraExcited"; // Using extraExcited for high energy play
    if (mood === "excited") return "extraExcited";

    // Default
    return "aariyaPersonality";
}
