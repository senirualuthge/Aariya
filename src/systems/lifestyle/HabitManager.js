/**
 * HabitManager.js
 * Interfaces with the local Python Habit Tracker API.
 */
export class HabitManager {
    constructor(apiBase = 'http://localhost:5000') {
        this.apiBase = apiBase;
    }

    /**
     * Fetches current habits and stats from the local server.
     * @returns {Promise<Array>} List of habits with streaks
     */
    async getHabitStats() {
        try {
            const response = await fetch(`${this.apiBase}/api/habits`);
            if (!response.ok) throw new Error('Habit Server Offline');
            return await response.json();
        } catch (error) {
            console.warn('[HabitManager] Failed to fetch habits:', error);
            return null;
        }
    }

    /**
     * formatting the habit data into a readable context string for the LLM.
     */
    async getContextString() {
        const habits = await this.getHabitStats();
        if (!habits || habits.length === 0) return "";

        const summary = habits.map(h => {
            const status = h.streak > 0 
                ? `${h.streak}-day streak!` 
                : (h.last_done ? `last done on ${h.last_done}` : `not started yet`);
            return `- ${h.name}: ${status}`;
        }).join('\n');

        return `\nUser's Habit Tracker Stats:\n${summary}\n(Use this to motivate or congratulate the user)`;
    }
}

export const habitManager = new HabitManager();
