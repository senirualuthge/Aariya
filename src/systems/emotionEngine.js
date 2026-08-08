// emotionEngine.js - Handles weighted blending and natural decay of emotions

/**
 * Emotion Decay Configuration
 * Rise: Fast (0.2–0.4s) -> handled by the setter logic in systems if needed, or by engine pulses.
 * Decay: Slow (2–6s) -> implemented here.
 */
const DECAY_RATES = {
    calm: 0.05,       // Calm is the floor, decays very slowly if pushed above 1.0
    happy: 0.15,      // Happy lasts a decent amount
    nervous: 0.25,    // Nervous fades relatively fast after the trigger
    angry: 0.1,       // Anger lingers (smolder effect)
    sad: 0.12,        // Sadness lingers
    surprised: 0.4,   // Surprise is very short-lived
    interest: 0.05,   // Interest is sustained
    confidence: 0.08, // Confidence is relatively stable
    concern: 0.15,    // Concern fades moderately
};

const BLEND_SPEED = 5.0; // Lerp speed for rising emotions

/**
 * Updates the emotion vector by applying decay and lerping towards target values.
 * @param {Object} currentEmotions - The current emotion weights from the store.
 * @param {Object} targetEmotions - The target intensity for each emotion.
 * @param {number} deltaTime - Time since last update in seconds.
 * @returns {Object} The updated emotion weights.
 */
export function updateEmotions(currentEmotions, targetEmotions, deltaTime) {
    const updated = { ...currentEmotions };

    Object.keys(updated).forEach(key => {
        const target = targetEmotions[key] || 0.0;
        const decayRate = DECAY_RATES[key] || 0.1;

        if (updated[key] < target) {
            // Rise: Move towards target at BLEND_SPEED
            updated[key] += (target - updated[key]) * BLEND_SPEED * deltaTime;
        } else {
            // Decay: Move towards target (usually 0) at decayRate
            // If target is 0, we decay naturally. If target is lower than current but > 0, we still decay.
            updated[key] -= (updated[key] - target) * decayRate * deltaTime;
        }

        // Failsafe: Clamp values between 0 and 1.5 (as per spec for behavior multipliers)
        // Note: For pure weights, 0-1 is normal, but especification allowed 0.2-1.5 for final values.
        // We'll keep weights primarily 0-1 but allow the "Calm" floor to be 1.0.
        updated[key] = Math.max(0, Math.min(updated[key], 1.5));
    });

    // Special Rule: Calm is the "home base"
    // If all other emotions are low, Calm should drift back to 1.0
    const otherEmotionSum = Object.entries(updated)
        .filter(([key]) => key !== 'calm')
        .reduce((sum, [, val]) => sum + val, 0);

    if (otherEmotionSum < 0.2) {
        updated.calm += (1.0 - updated.calm) * 0.5 * deltaTime;
    } else {
        // If other emotions are high, Calm decays/suppresses
        updated.calm -= updated.calm * 0.2 * deltaTime;
    }

    return updated;
}

/**
 * Calculates target emotions based on environmental stimuli (Audio, Silence, etc.)
 * Read.txt Rules:
 * - High Energy/Pitch -> Nervous/Fear
 * - Long Silence -> Bored/Calm (or Nervous if insecure)
 * - Positive Sentiment -> Happy (Handled by AI response, passed in as base)
 */
export function calculateEmotionTargets(currentTargets, audioStats, silenceDuration, currentPersonality) {
    const targets = { ...currentTargets };

    // 1. Audio Energy Rule (Calm -> Nervous)
    // "Calm -> Nervous if UserVoiceEnergy ↑"
    if (audioStats.isLoud) {
        // Sudden loud noise implies Fear or Nervousness
        targets.nervous = Math.max(targets.nervous, 0.8);
        targets.calm = 0.0;
        
        if (audioStats.energy > 80) { // Very loud
             targets.fear = Math.max(targets.fear, 0.6);
        }
    } else if (audioStats.energy > 50) { // Animated speech
        targets.interest = Math.max(targets.interest, 0.6);
        targets.calm = Math.max(targets.calm, 0.3); // Still composed
    }

    // 2. Silence Rule
    if (silenceDuration > 10.0) {
        // Long silence
        if (currentPersonality === 'calm') {
            targets.calm = 1.0;
            targets.happy = 0.0;
            targets.interest = 0.0;
        } else if (currentPersonality === 'shy') {
            targets.nervous = Math.max(targets.nervous, 0.4); // "Did I say something wrong?"
        }
    }

    return targets;
}
