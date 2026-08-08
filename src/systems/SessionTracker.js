import { useEffect, useRef } from 'react';
import useStore from '../store';
import { getDB } from '../db/init';
import { v4 as uuidv4 } from 'uuid';

export default function SessionTracker() {
    const sessionIdRef = useRef(null);
    const emotionHistoryRef = useRef([]);
    const { started } = useStore();

    useEffect(() => {
        if (!started) return;

        const db = getDB();
        
        // Get or create user
        const userId = 'user_default'; // TODO: Multi-user support later
        const userExists = db.prepare('SELECT user_id FROM users WHERE user_id = ?').get(userId);
        
        if (!userExists) {
            db.prepare('INSERT INTO users (user_id) VALUES (?)').run(userId);
        }

        // Start new session
        const sessionId = uuidv4();
        sessionIdRef.current = sessionId;
        useStore.getState().setSessionId(sessionId); // Store in Zustand
        
        const now = new Date().toISOString();
        db.prepare(`
            INSERT INTO sessions (session_id, user_id, start_time)
            VALUES (?, ?, ?)
        `).run(sessionId, userId, now);

        console.log('📊 Session started:', sessionId);

        // Update total sessions
        db.prepare('UPDATE users SET total_sessions = total_sessions + 1, last_session = ? WHERE user_id = ?')
            .run(now, userId);

        // Emotion tracking interval
        const emotionInterval = setInterval(() => {
            const { emotions, userEmotion } = useStore.getState();
            
            // Calculate valence from AI emotions (weighted)
            const valence = (
                emotions.happy * 0.8 +
                emotions.calm * 0.3 +
                emotions.surprised * 0.2 -
                emotions.sad * 0.6 -
                emotions.angry * 0.8
            );
            
            const arousal = (
                emotions.surprised * 0.9 +
                emotions.angry * 0.8 +
                emotions.nervous * 0.7 +
                emotions.happy * 0.5
            );

            emotionHistoryRef.current.push({
                timestamp: Date.now(),
                valence,
                arousal,
                userValence: userEmotion.valence,
                userArousal: userEmotion.arousal
            });

            // Keep last 100 samples
            if (emotionHistoryRef.current.length > 100) {
                emotionHistoryRef.current.shift();
            }
        }, 5000); // Sample every 5s

        // Session end handler
        const handleSessionEnd = () => {
            if (!sessionIdRef.current) return;

            const endTime = new Date().toISOString();
            const startTimeResult = db.prepare('SELECT start_time FROM sessions WHERE session_id = ?')
                .get(sessionIdRef.current);
            
            if (!startTimeResult) return;

            const startTime = new Date(startTimeResult.start_time);
            const durationSec = Math.floor((new Date(endTime) - startTime) / 1000);

            // Calculate metrics
            const { ecs, psi, valence_volatility, avg_valence, avg_arousal } = calculateMetrics(
                emotionHistoryRef.current
            );

            // Update session
            db.prepare(`
                UPDATE sessions 
                SET end_time = ?,
                    duration_sec = ?,
                    ecs = ?,
                    psi = ?,
                    valence_volatility = ?,
                    avg_valence = ?,
                    avg_arousal = ?,
                    nse = 1
                WHERE session_id = ?
            `).run(endTime, durationSec, ecs, psi, valence_volatility, avg_valence, avg_arousal, sessionIdRef.current);

            console.log('📊 Session ended:', {
                duration: durationSec + 's',
                ecs: ecs.toFixed(1),
                psi: psi.toFixed(2)
            });
        };

        // Listen for session end
        window.addEventListener('beforeunload', handleSessionEnd);

        return () => {
            clearInterval(emotionInterval);
            handleSessionEnd();
            window.removeEventListener('beforeunload', handleSessionEnd);
        };
    }, [started]);

    return null; // Logic-only component
}

// Calculate retention metrics
function calculateMetrics(emotionHistory) {
    if (emotionHistory.length === 0) {
        return { ecs: 50, psi: 0, valence_volatility: 0, avg_valence: 0, avg_arousal: 0 };
    }

    // Average valence/arousal
    const avg_valence = emotionHistory.reduce((sum, e) => sum + e.valence, 0) / emotionHistory.length;
    const avg_arousal = emotionHistory.reduce((sum, e) => sum + e.arousal, 0) / emotionHistory.length;

    // Valence volatility (standard deviation)
    const variance = emotionHistory.reduce((sum, e) => sum + Math.pow(e.valence - avg_valence, 2), 0) / emotionHistory.length;
    const valence_volatility = Math.sqrt(variance);

    // ECS (Emotional Continuity Score): 0-100
    // Low volatility + positive valence = high ECS
    const ecs = Math.max(0, Math.min(100, 
        50 + (avg_valence * 20) - (valence_volatility * 30)
    ));

    // PSI (Personality Satisfaction Index): -1 to +1
    // User mirrors AI tone = positive PSI
    const userAlignment = emotionHistory.slice(-10).reduce((sum, e, i, arr) => {
        if (i === 0) return 0;
        const userChange = e.userValence - arr[i-1].userValence;
        const aiChange = e.valence - arr[i-1].valence;
        return sum + (userChange * aiChange); // Positive if same direction
    }, 0) / 10;

    const psi = Math.max(-1, Math.min(1, userAlignment));

    return { ecs, psi, valence_volatility, avg_valence, avg_arousal };
}
