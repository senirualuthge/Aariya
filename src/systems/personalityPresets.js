// UE5 Personality Presets (behavior modulation)

export const PERSONALITY_PRESETS = {
    shy: {
        name: 'Shy',
        eyeContactTime: 0.4,
        headWeight: 0.35,
        gestureFrequency: 0.5,
        gestureScale: 0.5,
        emotionExpression: 0.6,
        reactionDelay: 150, // ms
        blinkMultiplier: 1.1,
        description: 'Reserved, avoids attention, small gestures'
    },
    
    calm: {
        name: 'Calm',
        eyeContactTime: 0.7,
        headWeight: 0.6,
        gestureFrequency: 1.0,
        gestureScale: 1.0,
        emotionExpression: 1.0,
        reactionDelay: 0,
        blinkMultiplier: 1.0,
        description: 'Neutral, grounded, emotionally stable (BASELINE)'
    },
    
    bubbly: {
        name: 'Bubbly',
        eyeContactTime: 0.85,
        headWeight: 0.75,
        gestureFrequency: 1.5,
        gestureScale: 1.3,
        emotionExpression: 1.4,
        reactionDelay: -50, // Eager responses
        blinkMultiplier: 0.9,
        description: 'Energetic, upbeat, expressive'
    },
    
    confident: {
        name: 'Confident',
        eyeContactTime: 0.9,
        headWeight: 0.85,
        gestureFrequency: 1.2,
        gestureScale: 1.2,
        emotionExpression: 1.3,
        reactionDelay: -50,
        blinkMultiplier: 0.8,
        description: 'Assertive, comfortable with attention'
    },
    
    cutie: {
        name: 'Cutie',
        eyeContactTime: 0.6,
        headWeight: 0.45,
        gestureFrequency: 0.7,
        gestureScale: 0.6,
        emotionExpression: 1.3,
        reactionDelay: 100,
        blinkMultiplier: 1.1,
        description: 'Soft, innocent, comforting'
    }
};

// Apply personality to behavior parameters
export function applyPersonalityModifiers(baseValue, personality, parameter) {
    const preset = PERSONALITY_PRESETS[personality] || PERSONALITY_PRESETS.calm;
    
    switch (parameter) {
        case 'gesture_intensity':
            return baseValue * preset.gestureScale;
        case 'emotion_expression':
            return baseValue * preset.emotionExpression;
        case 'blink_rate':
            return baseValue * preset.blinkMultiplier;
        case 'reaction_delay':
            return preset.reactionDelay;
        default:
            return baseValue;
    }
}

export function getPersonalityPreset(personalityName) {
    return PERSONALITY_PRESETS[personalityName] || PERSONALITY_PRESETS.calm;
}
