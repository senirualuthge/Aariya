import { getDB } from '../db/init';
import useStore from '../store';

export class MemorySystem {
    constructor() {
        this.db = getDB();
        this.userId = 'user_default';
    }

    // Store a memory
    storeMemory(content, type = 'short_term', importance = 0.5) {
        const { userEmotion, emotions } = useStore.getState();
        const sessionId = useStore.getState().sessionId || null;
        
        const emotionContext = JSON.stringify({
            userValence: userEmotion.valence,
            userArousal: userEmotion.arousal,
            aiEmotion: emotions
        });

        this.db.prepare(`
            INSERT INTO memories (user_id, session_id, type, content, emotion_context, importance)
            VALUES (?, ?, ?, ?, ?, ?)
        `).run(this.userId, sessionId, type, content, emotionContext, importance);
    }

    // Recall recent memories
    recallShortTerm(limit = 5) {
        return this.db.prepare(`
            SELECT content, emotion_context, timestamp
            FROM memories
            WHERE user_id = ? AND type = 'short_term'
            ORDER BY timestamp DESC
            LIMIT ?
        `).all(this.userId, limit);
    }

    // Recall important long-term memories
    recallLongTerm(limit = 3) {
        return this.db.prepare(`
            SELECT content, emotion_context, timestamp
            FROM memories
            WHERE user_id = ? AND type = 'long_term'
            ORDER BY importance DESC, timestamp DESC
            LIMIT ?
        `).all(this.userId, limit);
    }

    // Recall memories by keyword
    searchMemories(keyword, limit = 5) {
        return this.db.prepare(`
            SELECT content, emotion_context, timestamp, type
            FROM memories
            WHERE user_id = ? AND content LIKE ?
            ORDER BY importance DESC, timestamp DESC
            LIMIT ?
        `).all(this.userId, `%${keyword}%`, limit);
    }

    // Promote short-term memory to long-term
    promoteToLongTerm(memoryId) {
        this.db.prepare(`
            UPDATE memories
            SET type = 'long_term', importance = importance * 1.5
            WHERE memory_id = ?
        `).run(memoryId);
    }

    // Clean old short-term memories (keep last 24 hours)
    cleanOldMemories() {
        this.db.prepare(`
            DELETE FROM memories
            WHERE type = 'short_term'
            AND timestamp < datetime('now', '-1 day')
        `).run();
    }
}

// Singleton instance
let memorySystemInstance = null;

export function getMemorySystem() {
    if (!memorySystemInstance) {
        memorySystemInstance = new MemorySystem();
    }
    return memorySystemInstance;
}
