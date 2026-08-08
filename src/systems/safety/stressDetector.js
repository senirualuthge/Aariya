export function detectStress(text) {
    const stressWords = [
        "tired", "stressed", "overwhelmed", "exhausted", "burnout", 
        "can't take it", "too much", "anxious", "panic", "draining"
    ];
    const lower = text.toLowerCase();
    return stressWords.some(w => lower.includes(w));
}
