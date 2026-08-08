export class HabitTracker {
    constructor() {
        this.stats = null;
    }

    async getStats() {
        if (!window.electronAPI) {
            console.warn('Electron API not available');
            return null;
        }
        try {
            const output = await window.electronAPI.getHabitStats();
            console.log('Habit Stats Raw:', output);
            // Parse the CLI output
            // Expected format:
            // Habit Streaks:
            // - habit_name: X day streak
            // OR "No stats available..."
            
            const stats = {};
            const lines = output.split('\n');
            for (const line of lines) {
                const match = line.match(/- (.*): (\d+) day streak/);
                if (match) {
                    stats[match[1]] = parseInt(match[2], 10);
                }
            }
            this.stats = stats;
            return stats;
        } catch (err) {
            console.error('Failed to get habit stats:', err);
            return null;
        }
    }

    calculateMoodImpact() {
        if (!this.stats) return 0;
        
        let impact = 0;

        for (const [habit, streak] of Object.entries(this.stats)) {
            if (habit) { /* satisfy lint */ }
            if (streak > 0) impact += 0.1; // Boost for any streak
            if (streak > 5) impact += 0.2; // Boost for long streak
        }

        // If no habits done (empty stats but intended habits?), maybe penalty?
        // For now, positive reinforcement only.
        
        return Math.min(impact, 1.0); // Cap boost at 1.0
    }
}
