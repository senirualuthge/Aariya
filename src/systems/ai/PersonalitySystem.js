/**
 * src/systems/ai/PersonalitySystem.js
 * Defines Personality Templates (Bounds + Biases) and Logic.
 */

export const PERSONALITY_TEMPLATES = {
    Calm: {
        name: "Calm",
        axis_bounds: { energy: [0.0, 0.4], dominance: [0.0, 0.3], warmth: [0.4, 0.8] },
        emotion_bias: { calm: 1.5, happy: 0.8, nervous: 0.1 }, // Multipliers
        gesture_profile: { frequency: 0.3, variance: 0.2 },
        speech_modulation: { pace: 0.9, pitch_variance: 0.8 }
    },
    Bubbly: {
        name: "Bubbly",
        axis_bounds: { energy: [0.6, 1.0], dominance: [0.0, 0.4], warmth: [0.7, 1.0] },
        emotion_bias: { happy: 1.5, surprised: 1.2, calm: 0.3 },
        gesture_profile: { frequency: 0.9, variance: 0.8 },
        speech_modulation: { pace: 1.2, pitch_variance: 1.5 }
    },
    Confident: {
        name: "Confident",
        axis_bounds: { energy: [0.4, 0.7], dominance: [0.6, 0.9], warmth: [0.3, 0.7] },
        emotion_bias: { confidence: 1.5, nervous: 0.0, calm: 0.8 },
        gesture_profile: { frequency: 0.6, variance: 0.4, firm: true },
        speech_modulation: { pace: 1.0, pitch_variance: 0.9 }
    },
    Flirty: { // Requires Unlock / Consent
        name: "Flirty",
        axis_bounds: { energy: [0.5, 0.8], dominance: [0.2, 0.6], warmth: [0.8, 1.0] },
        emotion_bias: { interest: 1.4, happy: 1.1, shy: 0.5 },
        gesture_profile: { frequency: 0.7, head_tilt: true },
        speech_modulation: { pace: 0.85, pitch_variance: 1.2, whisper_chance: 0.3 }
    }
};

export class PersonalitySystem {
    constructor() {
        this.currentTemplate = PERSONALITY_TEMPLATES.Calm;
        this.currentAxes = { energy: 0.2, dominance: 0.1, warmth: 0.6 }; // -1 to 1
    }

    setTemplate(name) {
        if (PERSONALITY_TEMPLATES[name]) {
            this.currentTemplate = PERSONALITY_TEMPLATES[name];
            // Reset axes to mid-point of new bounds
            const bounds = this.currentTemplate.axis_bounds;
            this.currentAxes.energy = (bounds.energy[0] + bounds.energy[1]) / 2;
            this.currentAxes.warmth = (bounds.warmth[0] + bounds.warmth[1]) / 2;
        }
    }

    // Called by Neural Engine to nudges axes
    applyNeuralDelta(delta) {
        // Apply delta but clamp to Template Bounds
        const bounds = this.currentTemplate.axis_bounds;
        
        this.currentAxes.energy = this.clamp(
            this.currentAxes.energy + delta.energy, 
            bounds.energy[0], bounds.energy[1]
        );
        this.currentAxes.dominance = this.clamp(
            this.currentAxes.dominance + delta.dominance, 
            bounds.dominance[0], bounds.dominance[1]
        );
         this.currentAxes.warmth = this.clamp(
            this.currentAxes.warmth + delta.warmth, 
            bounds.warmth[0], bounds.warmth[1]
        );
    }

    clamp(val, min, max) {
        return Math.max(min, Math.min(val, max));
    }

    getBehaviorModifiers() {
        return {
            gestureDensity: this.currentTemplate.gesture_profile.frequency * (0.5 + this.currentAxes.energy),
            speechPace: this.currentTemplate.speech_modulation.pace,
            biases: this.currentTemplate.emotion_bias
        };
    }
}

export const personalitySystem = new PersonalitySystem();
