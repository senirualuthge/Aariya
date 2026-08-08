/**
 * src/systems/analytics/AnalyticsSystem.js
 * Implements the Retention Analytics Model (ECS, PSI, NSA).
 * Uses localStorage as a "Local Database" for privacy/simplicity.
 */

class AnalyticsSystem {
    constructor() {
        this.storageKey = 'AIGirl_Analytics_Sessions';
        this.userKey = 'AIGirl_Analytics_User';
        this.currentSession = null;
        
        // Load or Init User
        this.user = this.loadUser();
        
        // Start Session immediately? No, wait for explicit start or first interaction.
        // But for simplicity, we'll start on load if standard "Init" is called.
    }

    // --- DATA LAYER (Simulating SQL Tables) ---

    loadUser() {
        if (typeof window === 'undefined') return { user_id: 'server-mock', install_date: Date.now() };
        let user = JSON.parse(localStorage.getItem(this.userKey));
        if (!user) {
            user = {
                user_id: crypto.randomUUID(),
                install_date: Date.now(),
                last_session: null,
                metrics: { baseline_ecs: 80 }
            };
            this.saveUser(user);
        }
        return user;
    }

    saveUser(user) {
        if (typeof window !== 'undefined') localStorage.setItem(this.userKey, JSON.stringify(user));
        this.user = user;
    }

    getAllSessions() {
        if (typeof window === 'undefined') return [];
        return JSON.parse(localStorage.getItem(this.storageKey) || '[]');
    }

    saveSession(session) {
        if (typeof window === 'undefined') return;
        const sessions = this.getAllSessions();
        // Update if exists, else push
        const index = sessions.findIndex(s => s.session_id === session.session_id);
        if (index >= 0) {
            sessions[index] = session;
        } else {
            sessions.push(session);
        }
        localStorage.setItem(this.storageKey, JSON.stringify(sessions));
    }

    // --- SESSION LOGIC ---

    startSession() {
        // Close previous if open
        if (this.currentSession) this.endSession();

        const lastSession = this.getLastSession();
        
        this.currentSession = {
            session_id: crypto.randomUUID(),
            user_id: this.user.user_id,
            start_time: Date.now(),
            end_time: null,
            
            // Running Metrics
            ecs: 100, // Starts perfect, degrades if disconnected
            psi: 0.0, // Neutral
            nse: 0,   // Natural End?
            memory_success: 1.0, 
            
            // Temporary Tracking
            interactions: 0,
            emotion_consistency_hits: 0,
            emotion_consistency_attempts: 0
        };

        // Update User
        this.user.last_session = Date.now();
        this.saveUser(this.user);
        
        // Calculate Initial ECS (Return Latency Risk)
        if (lastSession) {
            // const hoursSince = (Date.now() - lastSession.end_time) / (1000 * 60 * 60);
            // Example: If > 48h, slight ECS penalty? Or strictly emotion based as per doc?
            // "Measures Tone consistency... User left calm -> returns stressed"
            // We'll update ECS in `checkEmotionalContinuity`
        }

        console.log("[Analytics] Session Started:", this.currentSession.session_id);
    }

    endSession(natural = false) {
        if (!this.currentSession) return;
        
        this.currentSession.end_time = Date.now();
        this.currentSession.nse = natural ? 1 : 0;
        
        this.saveSession(this.currentSession);
        console.log("[Analytics] Session Ended. Natural:", natural);
        this.currentSession = null;
    }

    getLastSession() {
        const sessions = this.getAllSessions();
        return sessions.length > 0 ? sessions[sessions.length - 1] : null;
    }

    // --- METRICS CALCULATION ---

    /**
     * Updates ECS based on "Emotional Continuity".
     * @param {string} userEmotion - Current user emotion
     * @param {string} expectedEmotion - Contextually appropriate emotion
     */
    trackEmotionalContinuity(userEmotion, expectedEmotion) {
        if (!this.currentSession) return;

        // Simple check: Is user's emotion "compatible" with expected?
        // e.g., if we expect 'calm' and they are 'calm', Good.
        // If we expect 'calm' and they are 'angry', Bad.
        
        const isCompatible = (userEmotion === expectedEmotion) || (userEmotion === 'neutral'); 
        
        this.currentSession.emotion_consistency_attempts++;
        if (isCompatible) this.currentSession.emotion_consistency_hits++;
        
        // Update ECS
        const ratio = this.currentSession.emotion_consistency_hits / this.currentSession.emotion_consistency_attempts;
        this.currentSession.ecs = Math.round(ratio * 100);
    }

    /**
     * Updates PSI (Personality Satisfaction)
     * @param {number} delta - +0.1 (good interaction) or -0.5 (correction)
     */
    updatePSI(delta) {
        if (!this.currentSession) return;
        // Clamp between -1 and 1
        this.currentSession.psi = Math.max(-1, Math.min(1, this.currentSession.psi + delta));
    }
    
    // --- QUERY REPORTING (Simulating SQL) ---
    
    getRetentionReport() {
        const sessions = this.getAllSessions();
        const firstUse = this.user.install_date;
        const now = Date.now();
        const daysSinceInstall = (now - firstUse) / (1000 * 60 * 60 * 24);
        
        // Count distinct days returned
        const distinctDays = new Set(sessions.map(s => new Date(s.start_time).toDateString()));
        
        return {
            dau: distinctDays.size, // Pseudo-DAU (days active)
            daysSinceInstall: Math.floor(daysSinceInstall),
            totalSessions: sessions.length,
            avgECS: sessions.reduce((sum, s) => sum + (s.ecs||0), 0) / (sessions.length||1)
        };
    }
}

export const analytics = new AnalyticsSystem();
