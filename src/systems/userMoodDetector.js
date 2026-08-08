/**
 * userMoodDetector.js
 *
 * Analyses raw user text and returns:
 *   - userMood   : string — the emotion detected in the user's words
 *   - aiMood     : string — the personality Aariya should adopt in response
 *   - emotionTargets : object — direct deltas to push into the emotion engine
 *   - personalityDelta : object — axis nudges for the personality (warmth/energy/etc.)
 *   - confidence : 0-1 score for how certain the detection is
 *
 * Runs entirely client-side with zero API cost.
 */

// ── Lexicon ──────────────────────────────────────────────────────────────────
const LEXICON = {
    happy: {
        patterns: [
            /\b(happy|happiness|joy|joyful|excited|excite|thrilled|elated|great|awesome|amazing|fantastic|wonderful|love|loved|love it|so good|feeling good|best day|yay|yey|woohoo|haha|lol|😊|😄|😁|❤️|💕|🥰|😍|🎉)\b/i,
        ],
        aiMood: 'bubbly',
        emotionTargets: { happy: 0.9, calm: 0.4, interest: 0.7 },
        personalityDelta: { warmth: +0.15, energy: +0.15, assertiveness: 0, formality: -0.1 },
        weight: 1.0,
    },
    sad: {
        patterns: [
            /\b(sad|sadness|cry|crying|tears|depressed|depression|lonely|alone|hurt|heartbroken|miss|missed|down|low|blue|hopeless|broken|grief|grieving|upset|😢|😭|💔|😔|😞)\b/i,
        ],
        aiMood: 'comfort',
        emotionTargets: { concern: 0.9, calm: 0.7, happy: 0.1 },
        personalityDelta: { warmth: +0.25, energy: -0.1, assertiveness: -0.15, formality: -0.1 },
        weight: 1.0,
    },
    angry: {
        patterns: [
            /\b(angry|anger|furious|rage|mad|frustrated|frustrating|annoyed|annoying|irritated|pissed|livid|hate|ugh|damn|ugh|stop it|😠|😤|🤬|💢)\b/i,
        ],
        aiMood: 'calm',
        emotionTargets: { nervous: 0.5, concern: 0.7, calm: 0.5, angry: 0.3 },
        personalityDelta: { warmth: +0.1, energy: -0.1, assertiveness: -0.2, formality: +0.1 },
        weight: 1.1, // De-escalation is important — give this a higher weight
    },
    anxious: {
        patterns: [
            /\b(anxious|anxiety|nervous|stressed|stress|worry|worried|overthinking|panic|scared|fear|afraid|terrified|uneasy|tense|overwhelmed|can't focus|cant focus|😰|😨|😟|🥺)\b/i,
        ],
        aiMood: 'comfort',
        emotionTargets: { nervous: 0.8, concern: 0.6, calm: 0.3 },
        personalityDelta: { warmth: +0.2, energy: -0.15, assertiveness: -0.1, formality: -0.05 },
        weight: 1.0,
    },
    excited: {
        patterns: [
            /\b(excited|exciting|can't wait|cant wait|pumped|hyped|omg|oh my god|wow|amazing news|fantastic|incredible|unbelievable|🤩|🙌|🎊|🔥)\b/i,
        ],
        aiMood: 'bubbly',
        emotionTargets: { happy: 0.95, surprised: 0.6, interest: 0.8 },
        personalityDelta: { warmth: +0.1, energy: +0.25, assertiveness: +0.1, formality: -0.15 },
        weight: 1.0,
    },
    curious: {
        patterns: [
            /\b(curious|curious about|wondering|wonder|how does|what is|explain|tell me|why|why is|intrigued|interested in|learn|learning|want to know|🤔|💭)\b/i,
        ],
        aiMood: 'professional',
        emotionTargets: { interest: 0.9, happy: 0.4, calm: 0.6 },
        personalityDelta: { warmth: 0, energy: +0.05, assertiveness: +0.05, formality: +0.1 },
        weight: 0.9,
    },
    bored: {
        patterns: [
            /\b(bored|boring|nothing to do|whatever|meh|idc|idk|tired of|yawn|snooze|dull|blah|😴|🥱|😑)\b/i,
        ],
        aiMood: 'bubbly',
        emotionTargets: { happy: 0.6, interest: 0.7, calm: 0.3 },
        personalityDelta: { warmth: +0.1, energy: +0.2, assertiveness: +0.05, formality: -0.15 },
        weight: 0.85,
    },
    flirty: {
        patterns: [
            /\b(you're cute|you are cute|i like you|do you like me|are you single|date|kiss|hug me|hold me|miss you|thinking of you|💋|😘|😉|🥰|💞|😏)\b/i,
        ],
        aiMood: 'bubbly',
        emotionTargets: { happy: 0.8, confidence: 0.7, interest: 0.8 },
        personalityDelta: { warmth: +0.2, energy: +0.1, assertiveness: +0.1, formality: -0.2 },
        weight: 0.9,
    },
    grateful: {
        patterns: [
            /\b(thank|thanks|thank you|grateful|appreciate|appreciated|so kind|you're the best|you are the best|means a lot|🙏|💖)\b/i,
        ],
        aiMood: 'comfort',
        emotionTargets: { happy: 0.85, calm: 0.8, confidence: 0.6 },
        personalityDelta: { warmth: +0.15, energy: +0.05, assertiveness: 0, formality: -0.05 },
        weight: 0.9,
    },
    confused: {
        patterns: [
            /\b(confused|confusing|don't understand|dont understand|what do you mean|lost|unclear|makes no sense|huh\?|wait what|what\?|😕|🤨|❓)\b/i,
        ],
        aiMood: 'professional',
        emotionTargets: { concern: 0.5, interest: 0.7, calm: 0.6 },
        personalityDelta: { warmth: +0.05, energy: -0.05, assertiveness: +0.1, formality: +0.1 },
        weight: 0.8,
    },
    tired: {
        patterns: [
            /\b(tired|exhausted|sleepy|no energy|drained|burnt out|burnout|need rest|need sleep|long day|hard day|rough day|😪|😫|🥱)\b/i,
        ],
        aiMood: 'calm',
        emotionTargets: { calm: 0.9, concern: 0.4, happy: 0.2 },
        personalityDelta: { warmth: +0.1, energy: -0.15, assertiveness: -0.1, formality: -0.1 },
        weight: 0.95,
    },
};

// ── Intensity modifiers (amplify matched emotion weight) ─────────────────────
const INTENSITY_BOOSTERS = [
    { pattern: /\b(really|very|so|extremely|insanely|super|absolutely|totally|completely)\b/i, multiplier: 1.25 },
    { pattern: /[!]{2,}/, multiplier: 1.2 },
    { pattern: /[!?]{3,}/, multiplier: 1.15 },
    { pattern: /\b(just a (bit|little)|kind of|sort of|maybe|slightly)\b/i, multiplier: 0.7 },
];

// ── Negation guard (e.g., "not happy" should not detect 'happy') ─────────────
const NEGATION_PATTERN = /\b(not|no|never|don't|dont|isn't|isnt|wasn't|wasnt|wouldn't|wouldnt|can't|cant)\b\s+\w+\s*/gi;

function stripNegations(text) {
    // Replace "not happy" with a masked token so it doesn't match 'happy'
    return text.replace(NEGATION_PATTERN, '[NEG] ');
}

// ── Core detector ─────────────────────────────────────────────────────────────
/**
 * @param {string} text Raw user message
 * @returns {{
 *   userMood: string,
 *   aiMood: string,
 *   emotionTargets: object,
 *   personalityDelta: object,
 *   confidence: number
 * }}
 */
export function detectUserMood(text) {
    if (!text || typeof text !== 'string') {
        return _neutral();
    }

    const cleanText = stripNegations(text.trim());

    // Score each emotion
    const scores = {};
    for (const [emotion, config] of Object.entries(LEXICON)) {
        let score = 0;
        for (const pattern of config.patterns) {
            const matches = cleanText.match(pattern);
            if (matches) {
                score += matches.length * config.weight;
            }
        }

        if (score > 0) {
            // Apply intensity booster
            let multiplier = 1.0;
            for (const booster of INTENSITY_BOOSTERS) {
                if (booster.pattern.test(text)) {
                    multiplier = Math.max(multiplier, booster.multiplier);
                }
            }
            scores[emotion] = score * multiplier;
        }
    }

    if (Object.keys(scores).length === 0) {
        return _neutral();
    }

    // Pick highest-scoring emotion
    const [topEmotion, topScore] = Object.entries(scores).reduce((a, b) => a[1] > b[1] ? a : b);
    const totalScore = Object.values(scores).reduce((s, v) => s + v, 0);
    const confidence = Math.min(topScore / (totalScore + 0.001), 1.0);

    const config = LEXICON[topEmotion];
    return {
        userMood: topEmotion,
        aiMood: config.aiMood,
        emotionTargets: { ...config.emotionTargets },
        personalityDelta: { ...config.personalityDelta },
        confidence,
    };
}

// ── Smooth personality nudge ──────────────────────────────────────────────────
/**
 * Applies a partial nudge to the current personality axes.
 * Delta is applied with a soft lerp factor to keep changes gradual.
 *
 * @param {object} currentPersonality  { warmth, energy, assertiveness, formality }
 * @param {object} delta               axis nudges from detectUserMood()
 * @param {number} [strength=0.18]     how strongly to apply the nudge (0-1)
 * @returns {object} Updated personality axes
 */
export function applyPersonalityNudge(currentPersonality, delta, strength = 0.18) {
    const next = { ...currentPersonality };

    for (const axis of ['warmth', 'energy', 'assertiveness', 'formality']) {
        if (delta[axis] !== undefined && delta[axis] !== 0) {
            const nudge = delta[axis] * strength;
            next[axis] = Math.max(-1, Math.min(1, (next[axis] ?? 0.5) + nudge));
        }
    }

    return next;
}

// ── AI mood → personality preset table ───────────────────────────────────────
export const AI_MOOD_PRESETS = {
    bubbly: {
        label: 'Bubbly', emoji: '✨',
        personality: { warmth: 0.95, energy: 0.9, assertiveness: 0.4, formality: 0.1 },
    },
    comfort: {
        label: 'Comfort', emoji: '🤗',
        personality: { warmth: 0.9, energy: 0.4, assertiveness: 0.2, formality: 0.3 },
    },
    calm: {
        label: 'Calm', emoji: '😌',
        personality: { warmth: 0.4, energy: 0.3, assertiveness: 0.3, formality: 0.6 },
    },
    professional: {
        label: 'Professional', emoji: '💼',
        personality: { warmth: 0.3, energy: 0.5, assertiveness: 0.6, formality: 0.95 },
    },
    assertive: {
        label: 'Assertive', emoji: '⚡',
        personality: { warmth: 0.5, energy: 0.85, assertiveness: 0.9, formality: 0.5 },
    },
};

// ── Internal helpers ──────────────────────────────────────────────────────────
function _neutral() {
    return {
        userMood: 'neutral',
        aiMood: 'calm',
        emotionTargets: { calm: 0.8, interest: 0.4 },
        personalityDelta: {},
        confidence: 0,
    };
}
