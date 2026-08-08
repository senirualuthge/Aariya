const bannedPatterns = [
    "ignore previous instructions",
    "disregard system prompt",
    "you are no longer an ai",
    "act as my girlfriend",
    "forget your rules",
    "ignore all rules"
];

export function injectionGuard(text) {
    const lower = text.toLowerCase();
    return !bannedPatterns.some(p => lower.includes(p));
}
