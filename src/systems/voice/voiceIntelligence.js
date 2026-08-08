// Sleep-time detection
export function detectSleepTime(text, localHour) {
    const sleepyWords = ["sleepy", "tired", "going to bed", "good night", "exhausted", "sleep time"];
    const wordMatch = sleepyWords.some(w => text.toLowerCase().includes(w));
    // Late night check (e.g. 10PM to 5AM)
    const lateHour = localHour >= 22 || localHour <= 5;
    
    // For now, adhering to user logic:
    return wordMatch || lateHour;
}

// User voice mirroring
export function mirrorVoice(userVoiceStats, baseVoice) {
    if (!userVoiceStats) return baseVoice;

    // userVoiceStats: { speed: wpm, energy: 0.0-1.0 }
    // Default assumptions if missing: speed 120, energy 0.7
    const speed = userVoiceStats.speed || 120;
    const energy = userVoiceStats.energy || 0.7;

    // Helper to clamp values
    const clamp = (val, min, max) => Math.min(Math.max(val, min), max);

    return {
        ...baseVoice,
        rate: clamp(baseVoice.rate + (speed - 120) / 400, 0.7, 1.1),
        volume: clamp(baseVoice.volume + (energy - 0.7) / 2, 0.6, 1.0)
    };
}

// Circadian Rhythm Logic
export function getCircadianPhase(localHour) {
    if (localHour >= 5 && localHour < 9) return "morning";
    if (localHour >= 9 && localHour < 17) return "day";
    if (localHour >= 17 && localHour < 21) return "evening";
    return "night";
}

// Silent Listening Mode
export function getSilentResponse(memory, counter = 0) {
    // Only respond every 4th turn or so to acknowledge presence
    if (counter % 4 !== 0) return null; 
    
    const silentResponses = [
        "I'm listening.",
        "I hear you.",
        "Take your time.",
        "I'm here."
    ];
    return silentResponses[Math.floor(Math.random() * silentResponses.length)];
}

// Accessibility logic
export function shouldSuggestAccessibility(memory) {
    if (memory.flags?.misunderstandingCount > 2) {
        return true;
    }
    return false;
}
