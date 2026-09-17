/**
 * sentimentAnalyzer.js
 * REAL sentiment analysis — no simulated API responses.
 *
 * Two honest paths:
 *   1. Google Cloud Natural Language API when VITE_GOOGLE_CLOUD_API_KEY is
 *      configured (real HTTP call, real scores).
 *   2. Otherwise a local lexical scorer computed from the actual text:
 *      valence-weighted word matches with intensifier/negation handling,
 *      normalized to [-1, 1]. Results carry method:'local-lexical' so
 *      callers know exactly which path produced them.
 */

const POSITIVE = {
    happy: 2, great: 2, amazing: 3, love: 3, best: 2, wonderful: 3, excellent: 3,
    good: 1, nice: 1, awesome: 3, fantastic: 3, glad: 2, thanks: 1, thank: 1,
    fun: 2, enjoy: 2, enjoyed: 2, perfect: 3, beautiful: 2, cool: 1, yay: 2,
};
const NEGATIVE = {
    bad: -1, hate: -3, worst: -3, terrible: -3, awful: -3, angry: -2, mad: -2,
    sad: -2, cry: -2, crying: -2, unhappy: -2, bummed: -2, upset: -2, annoyed: -1,
    horrible: -3, disgusting: -3, painful: -2, tired: -1, exhausted: -1, lonely: -2,
    alone: -1, stressed: -2, worried: -2, scared: -2, anxious: -2, sorry: -1,
};
const INTENSIFIERS = new Set(['very', 'really', 'so', 'extremely', 'super', 'absolutely', 'totally']);
const NEGATORS = new Set(['not', "n't", 'never', 'no', 'hardly', 'barely']);

export class SentimentAnalyzer {
    constructor() {
        // Real key only; no placeholder strings.
        this.apiKey = (typeof import.meta !== 'undefined' &&
                       import.meta.env?.VITE_GOOGLE_CLOUD_API_KEY) || null;
    }

    /**
     * Analyzes the sentiment of the provided text.
     * @param {string} text
     * @returns {Promise<Object>} { score, magnitude, primaryEmotion, method }
     */
    async analyze(text) {
        if (!text) return { score: 0, magnitude: 0, primaryEmotion: 'neutral', method: 'empty' };

        if (this.apiKey) {
            try {
                return await this.analyzeWithGoogle(text);
            } catch (error) {
                console.error('[Sentiment] Google API failed, using local-lexical:', error.message);
            }
        }
        return this.analyzeLocalLexical(text);
    }

    async analyzeWithGoogle(text) {
        const response = await fetch(
            `https://language.googleapis.com/v1/documents:analyzeSentiment?key=${this.apiKey}`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    document: { content: text, type: 'PLAIN_TEXT' },
                }),
                signal: AbortSignal.timeout(8000),
            }
        );
        if (!response.ok) throw new Error(`Google NL API ${response.status}`);
        const data = await response.json();
        const { score, magnitude } = data.documentSentiment;

        let primaryEmotion = 'neutral';
        if (score > 0.3) primaryEmotion = 'happy';
        else if (score < -0.6) primaryEmotion = 'angry';
        else if (score < -0.2) primaryEmotion = 'sad';
        else if (magnitude > 0.8) primaryEmotion = 'surprised';

        return { score, magnitude, primaryEmotion, method: 'google-nl-api' };
    }

    /**
     * Local lexical sentiment: genuinely computed from the words present.
     * Negators flip the following valence word; intensifiers boost it.
     */
    analyzeLocalLexical(text) {
        const tokens = String(text).toLowerCase().match(/[a-z']+/g) || [];

        let total = 0;
        let hits = 0;
        for (let i = 0; i < tokens.length; i++) {
            const tok = tokens[i];
            let v = POSITIVE[tok];
            if (v === undefined) v = NEGATIVE[tok];
            if (v === undefined) continue;

            // Look back one token for negation / intensification.
            const prev = tokens[i - 1] || '';
            const prev2 = tokens[i - 2] || '';
            let weight = 1;
            if (INTENSIFIERS.has(prev) || INTENSIFIERS.has(prev2)) weight = 1.5;
            if (NEGATORS.has(prev) || prev.endsWith("n't") ||
                NEGATORS.has(prev2)) v = -v * 0.8;

            total += v * weight;
            hits++;
        }

        // Normalize to [-1, 1]; scale by hits so long neutral texts → ~0.
        const score = hits > 0
            ? Math.max(-1, Math.min(1, total / (hits * 2)))
            : 0;
        const magnitude = Math.min(1, Math.abs(total) / (2 + hits));

        let primaryEmotion = 'neutral';
        if (score > 0.25) primaryEmotion = 'happy';
        else if (score < -0.5) primaryEmotion = 'angry';
        else if (score < -0.15) primaryEmotion = 'sad';

        return { score, magnitude, primaryEmotion, method: 'local-lexical' };
    }
}

export const sentimentAnalyzer = new SentimentAnalyzer();
