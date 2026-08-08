/**
 * src/systems/memory/AdvancedMemoryManager.js
 * Implements the 3-Layer Memory Schema from read.txt
 */

export class AdvancedMemoryManager {
    constructor() {
        // A. SHORT-TERM MEMORY (STM) - Seconds/Minutes
        this.stm = {
            buffer: [], // Rolling buffer of last ~30s of interactions
            userState: { valence: 0.0, arousal: 0.0, engagement: 0.5 },
            interactionState: { 
                 lastTimestamp: Date.now(),
                 speechRate: 1.0,
                 pauseAvgMs: 500
            }
        };

        // B. MID-TERM MEMORY (MTM) - Session based
        this.mtm = {
            sessionId: crypto.randomUUID(),
            startTime: Date.now(),
            topics: new Set(),
            emotionTrend: { avgValence: 0.0, volatility: 0.0 },
            responseEffectiveness: { calm: 0.5, bubbly: 0.5, confident: 0.5 }, // Learning weights
            boundaries: { flirty_rejected: false }
        };

        // C. LONG-TERM MEMORY (LTM) - Persistent
        this.ltm = this.loadLTM() || {
            userProfile: {
                name: "User",
                interactionPreference: "neutral", // friendly, intellectual, flirty
                emotionalSensitivity: "medium"
            },
            personalityConstraints: {
                warmthFloor: 0.3,
                maxEnergy: 0.8
            },
            hardBoundaries: {
                no_flirting: false,
                no_arrogance: true
            }
        };

        this.saveInterval = setInterval(() => this.persistLTM(), 10000); // Save LTM every 10s
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
     * @param {Object} metadata - { emotion, timestamp, audioStats }
     */
    addInteraction(role, content, metadata = {}) {
        const timestamp = Date.now();
        const entry = { role, content, timestamp, ...metadata };

        // 1. Update STM (Buffer)
        this.stm.buffer.push(entry);
        // Keep buffer small (last 20 items)
        if (this.stm.buffer.length > 20) this.stm.buffer.shift();

        // 2. Update STM State (if User)
        if (role === 'user') {
            this.stm.interactionState.lastTimestamp = timestamp;
            if (metadata.audioStats) {
                // Update arousal based on volume/energy
                this.stm.userState.arousal = (this.stm.userState.arousal * 0.7) + (metadata.audioStats.energy / 255 * 0.3);
            }
        }

        // 3. Update MTM (Topic Tracking - simplified)
        // In a real system, we'd extract topics here.
        // this.mtm.topics.add(...);
        
        // 4. Update MTM (Emotion Trend)
        if (metadata.emotion) {
            // Rough rolling average
            // Map emotion strings to valence for trend?
        }
    }

    /**
     * Returns recent context for LLM prompt construction.
     */
    getRecentContext() {
        return this.stm.buffer.map(item => `${item.role}: ${item.content}`).join('\n');
    }

    /**
     * Updates the persistent user profile based on observed behavior.
     */
    updateUserProfile(key, value) {
        this.ltm.userProfile[key] = value;
        this.persistLTM();
    }

    /**
     * Retrieves relevant context based on a query string (Simulation of Vector Search).
     * @param {string} query - The user's input to find related memories for.
     */
    retrieveContext(query) {
        if (!query) return [];
        
        const keywords = query.toLowerCase().split(' ').filter(w => w.length > 3);
        const results = [];
        
        // Search STM (Buffer)
        this.stm.buffer.forEach(msg => {
            const score = keywords.reduce((acc, k) => acc + (msg.content.toLowerCase().includes(k) ? 1 : 0), 0);
            if (score > 0) results.push({ ...msg, score, source: 'STM' });
        });

        // Search MTM (Session - requires maintaining a history array in MTM, which we haven't fully implemented yet)
        // For now, we only have STM buffer. 
        // TODO: Expand MTM to hold full session logs for this to work better.

        // Sort by relevance
        return results.sort((a, b) => b.score - a.score).slice(0, 3);
    }
}

export const advancedMemory = new AdvancedMemoryManager();
