const MUSIC_MAP = {
    calm: "ambient_soft",
    happy: "light_warm",
    stressed: "slow_pad",
    night: "sleep_ambient"
};

export function shouldPlayMusic(memory) {
    if (memory.safety.dependencyRisk !== "low") return false;
    
    // Check specific moods
    const mood = memory.context?.mood;
    if (mood === "stressed") return true;
    if (mood === "calm") return true;
    
    // Check night mode
    // We might pass an isNightMode flag or check time here, but usually memory reflects context
    
    return false;
}

export function getMusicTrack(mood) {
    return MUSIC_MAP[mood] || null;
}
