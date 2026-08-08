import { useEffect } from 'react';
import useStore from '../store';
import { getDB } from '../db/init';
import { neuralEngine } from './ai/NeuralEngine';

export default function PersonalitySystem() {
    const { started } = useStore();

    useEffect(() => {
        if (!started) return;

        const db = getDB();
        const userId = 'user_default';

        // Load existing personality or initialize
        const existing = db.prepare(`
            SELECT warmth, energy, assertiveness, formality 
            FROM personality_snapshots 
            WHERE user_id = ? 
            ORDER BY timestamp DESC 
            LIMIT 1
        `).get(userId);

        if (existing) {
            useStore.getState().setPersonality(existing);
        } else {
            // Initialize with neutral personality
            const initialPersonality = {
                warmth: 0.0,
                energy: 0.5,
                assertiveness: 0.5,
                formality: 0.5
            };
            useStore.getState().setPersonality(initialPersonality);
            
            // Save initial snapshot
            db.prepare(`
                INSERT INTO personality_snapshots (user_id, warmth, energy, assertiveness, formality)
                VALUES (?, ?, ?, ?, ?)
            `).run(userId, initialPersonality.warmth, initialPersonality.energy, 
                   initialPersonality.assertiveness, initialPersonality.formality);
        }

        // Weekly personality update (run on mount if > 7 days since last)
        const lastSnapshot = db.prepare(`
            SELECT timestamp FROM personality_snapshots 
            WHERE user_id = ? 
            ORDER BY timestamp DESC 
            LIMIT 1
        `).get(userId);

        if (lastSnapshot) {
            const daysSince = (Date.now() - new Date(lastSnapshot.timestamp)) / (1000 * 60 * 60 * 24);
            if (daysSince >= 7) {
                updatePersonality(db, userId);
            }
        }

        // Set up weekly timer (check every day, update if needed)
        const dailyCheck = setInterval(() => {
            const lastCheck = db.prepare(`
                SELECT timestamp FROM personality_snapshots 
                WHERE user_id = ? 
                ORDER BY timestamp DESC 
                LIMIT 1
            `).get(userId);

            if (lastCheck) {
                const daysSince = (Date.now() - new Date(lastCheck.timestamp)) / (1000 * 60 * 60 * 24);
                if (daysSince >= 7) {
                    updatePersonality(db, userId);
                }
            }
        }, 24 * 60 * 60 * 1000); // Check daily

        return () => clearInterval(dailyCheck);
    }, [started]);

    return null; // Logic-only
}

// Update personality via EMA (Exponential Moving Average)
function updatePersonality(db, userId) {
    // Get sessions from last 7 days
    const sessions = db.prepare(`
        SELECT avg_valence, avg_arousal, valence_volatility, duration_sec
        FROM sessions
        WHERE user_id = ?
        AND start_time >= datetime('now', '-7 days')
    `).all(userId);

    if (sessions.length === 0) return;

    // Calculate aggregate metrics
    const stats = {
        avg_valence: sessions.reduce((sum, s) => sum + s.avg_valence, 0) / sessions.length,
        avg_arousal: sessions.reduce((sum, s) => sum + s.avg_arousal, 0) / sessions.length,
        valence_volatility: sessions.reduce((sum, s) => sum + s.valence_volatility, 0) / sessions.length
    };

    // Get current personality
    const current = db.prepare(`
        SELECT warmth, energy, assertiveness, formality 
        FROM personality_snapshots 
        WHERE user_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 1
    `).get(userId);

    // Delegate to Neural Engine
    const newPersonality = neuralEngine.calculatePersonalityEvolution(current, stats);

    // Save new snapshot
    db.prepare(`
        INSERT INTO personality_snapshots (user_id, warmth, energy, assertiveness, formality)
        VALUES (?, ?, ?, ?, ?)
    `).run(userId, newPersonality.warmth, newPersonality.energy, newPersonality.assertiveness, newPersonality.formality);

    // Update store
    useStore.getState().setPersonality(newPersonality);

    console.log('🧠 Personality updated:', {
        warmth: newPersonality.warmth.toFixed(2),
        energy: newPersonality.energy.toFixed(2),
        assertiveness: newPersonality.assertiveness.toFixed(2),
        formality: newPersonality.formality.toFixed(2)
    });
}


