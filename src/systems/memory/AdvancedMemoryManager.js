/**
 * src/systems/memory/AdvancedMemoryManager.js
 * Implements the 3-Layer Memory Schema from read.txt
 *
 *   STM — a short rolling window of the most recent interactions.
 *   MTM — the full (bounded) session log plus derived topics/emotion trend.
 *   LTM — the persistent user profile (localStorage).
 *
 * Everything here is derived from real interactions passed in by the caller
 * (see src/systems/aiEngine.js); nothing is seeded or fabricated.
 */

// Bounded sizes for the in-memory tiers.
const STM_MAX = 20;          // keep the last N interactions as "short term"
const MTM_MAX = 500;         // full session log cap
const TREND_MAX = 100;       // rolling valence sample window
const TOPIC_MIN_LENGTH = 4;  // ignore very short tokens when extracting topics

// Common English stop-words filtered out of topic extraction. This is a code
// constant (language data), not fabricated runtime data.
const STOPWORDS = new Set([
    'this', 'that', 'with', 'have', 'from', 'they', 'them', 'then', 'than',
    'there', 'their', 'what', 'when', 'where', 'which', 'while', 'about',
    'would', 'could', 'should', 'your', 'yours', 'youre', 'just', 'like',
    'want', 'need', 'really', 'very', 'some', 'into', 'over', 'also', 'been',
    'were', 'will', 'well', 'dont', 'cant', 'wont', 'yeah', 'okay', 'ok',
]);

// Documented label → valence mapping. Only used when the caller supplies a
// *named* emotion and no numeric valence; unknown labels are ignored rather
// than guessed.
const EMOTION_VALENCE = {
    happy: 1.0, excited: 0.6, grateful: 0.8, calm: 0.2, neutral: 0.0,
    surprised: 0.1, anxious: -0.5, sad: -0.8, angry: -0.9, frustrated: -0.7,
};

function tokenize(text) {
    return String(text ?? '')
        .toLowerCase()
        .replace(/[^a-z0-9'\s]/g, ' ')
        .split(/\s+/)
        .filter(Boolean);
}

function valenceFromMetadata(metadata = {}) {
    if (typeof metadata.valence === 'number' && Number.isFinite(metadata.valence)) {
        return metadata.valence;
    }
    const label = typeof metadata.emotion === 'string' ? metadata.emotion.toLowerCase() : '';
    return Object.prototype.hasOwnProperty.call(EMOTION_VALENCE, label)
        ? EMOTION_VALENCE[label]
        : null; // unknown → contribute nothing (no invention)
}

export class AdvancedMemoryManager {
    constructor() {
        // A. SHORT-TERM MEMORY (STM) - Seconds/Minutes
        this.stm = {
            buffer: [], // Rolling buffer of last N interactions (refs into MTM)
            userState: { valence: 0.0, arousal: 0.0, engagement: 0.5 },
            interactionState: {
                lastTimestamp: Date.now(),
                speechRate: 1.0,
                pauseAvgMs: 500,
            },
        };

        // B. MID-TERM MEMORY (MTM) - Session based
        this.mtm = {
            sessionId: (globalThis.crypto?.randomUUID?.() ?? `sess-${Date.now()}`),
            startTime: Date.now(),
            history: [],          // full session log (bounded to MTM_MAX)
            topicCounts: new Map(),
            valenceSeries: [],    // rolling samples for the emotion trend
            emotionTrend: { avgValence: 0.0, volatility: 0.0, samples: 0 },
            boundaries: { flirty_rejected: false },
        };

        // C. LONG-TERM MEMORY (LTM) - Persistent
        this.ltm = this.loadLTM() || {
            userProfile: {
                name: "User",
                interactionPreference: "neutral", // friendly, intellectual, flirty
                emotionalSensitivity: "medium",
            },
            personalityConstraints: {
                warmthFloor: 0.3,
                maxEnergy: 0.8,
            },
            hardBoundaries: {
                no_flirting: false,
                no_arrogance: true,
            },
        };

        this.saveInterval = setInterval(() => this.persistLTM(), 10000);
        // Don't let the persistence timer keep a Node process alive (e.g. tests).
        this.saveInterval?.unref?.();
    }

    // ... Implementation methods ...
    loadLTM() {
        if (typeof window === 'undefined') return null;
        try {
            const data = localStorage.getItem('AIGirl_LTM');
            return data ? JSON.parse(data) : null;
        } catch (e) {
            console.error("LTM Load Failed", e);
            return null;
        }
    }

    persistLTM() {
        if (typeof window === 'undefined') return;
        try {
            localStorage.setItem('AIGirl_LTM', JSON.stringify(this.ltm));
        } catch (e) { console.error("LTM Save Failed", e); }
    }

    /**
     * Adds a new interaction to Short-Term Memory and updates Mid-Term stats.
     * @param {string} role - 'user' or 'ai'
     * @param {string} content - Text content
     * @param {Object} metadata - { emotion, score, valence, timestamp, audioStats }
     */
    addInteraction(role, content, metadata = {}) {
        const timestamp = metadata.timestamp || Date.now();
        const entry = { role, content, timestamp, ...metadata };

        // 1. Update STM (rolling buffer of the most recent interactions) and
        //    MTM (the full bounded session log). They share entry references so
        //    retrieval can label each MTM hit as STM-recent or deeper MTM.
        this.stm.buffer.push(entry);
        if (this.stm.buffer.length > STM_MAX) this.stm.buffer.shift();

        this.mtm.history.push(entry);
        if (this.mtm.history.length > MTM_MAX) this.mtm.history.shift();

        // 2. Update STM State (if User)
        if (role === 'user') {
            this.stm.interactionState.lastTimestamp = timestamp;
            if (metadata.audioStats?.energy != null) {
                // Update arousal based on volume/energy
                this.stm.userState.arousal =
                    (this.stm.userState.arousal * 0.7) + (metadata.audioStats.energy / 255 * 0.3);
            }
        }

        // 3. Update MTM topics — real term counts over the interaction text.
        for (const token of tokenize(content)) {
            if (token.length >= TOPIC_MIN_LENGTH && !STOPWORDS.has(token)) {
                this.mtm.topicCounts.set(token, (this.mtm.topicCounts.get(token) || 0) + 1);
            }
        }

        // 4. Update MTM emotion trend from the caller-supplied signal.
        const valence = valenceFromMetadata(metadata);
        if (valence != null) {
            const series = this.mtm.valenceSeries;
            series.push(valence);
            if (series.length > TREND_MAX) series.shift();
            const avg = series.reduce((a, b) => a + b, 0) / series.length;
            const variance = series.reduce((a, b) => a + (b - avg) ** 2, 0) / series.length;
            this.mtm.emotionTrend = {
                avgValence: avg,
                volatility: Math.sqrt(variance),
                samples: series.length,
            };
        }

        return entry;
    }

    /**
     * Returns recent context for LLM prompt construction.
     */
    getRecentContext() {
        return this.stm.buffer.map(item => `${item.role}: ${item.content}`).join('\n');
    }

    /**
     * The most salient topics of the session, derived from real term counts.
     * @param {number} limit
     * @returns {Array<{topic: string, count: number}>}
     */
    getTopicSummary(limit = 5) {
        return [...this.mtm.topicCounts.entries()]
            .sort((a, b) => b[1] - a[1])
            .slice(0, limit)
            .map(([topic, count]) => ({ topic, count }));
    }

    /**
     * Updates the persistent user profile based on observed behavior.
     */
    updateUserProfile(key, value) {
        this.ltm.userProfile[key] = value;
        this.persistLTM();
    }

    /**
     * Retrieves relevant context: real keyword scoring across the whole
     * session (MTM), with each hit labelled STM (recent) or MTM (deeper).
     * @param {string} query - The user's input to find related memories for.
     */
    retrieveContext(query) {
        if (!query) return [];

        const keywords = tokenize(query).filter(w => w.length > 3);
        if (keywords.length === 0) return [];

        const recent = new Set(this.stm.buffer);
        const results = [];

        this.mtm.history.forEach(msg => {
            const haystack = String(msg.content ?? '').toLowerCase();
            const score = keywords.reduce((acc, k) => acc + (haystack.includes(k) ? 1 : 0), 0);
            if (score > 0) {
                results.push({ ...msg, score, source: recent.has(msg) ? 'STM' : 'MTM' });
            }
        });

        // Rank by relevance, breaking ties by recency.
        return results
            .sort((a, b) => (b.score - a.score) || (b.timestamp - a.timestamp))
            .slice(0, 3);
    }
}

export const advancedMemory = new AdvancedMemoryManager();
export const MEMORY_TIERS = { STM_MAX, MTM_MAX, TREND_MAX };
