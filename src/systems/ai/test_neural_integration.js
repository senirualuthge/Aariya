
import { neuralEngine } from './NeuralEngine.js';

console.log("🧪 Starting Neural Engine Integration Test...");

// Mock State
const mockState = {
    emotions: { sad: 0, angry: 0, happy: 0, arousal: 0 },
    personality: { warmth: 0.5, assertiveness: 0.5 },
    socialIntent: { intent: 'LISTENING', warmth: 0.5, dominance: 0.5, openness: 0.5, engagement: 0.5 }
};

// Test 1: High Sadness -> Comforting
console.log("\nTest 1: High Sadness -> Comforting");
mockState.emotions.sad = 0.8;
const intent1 = neuralEngine.resolveSocialIntent(mockState, 1.0);
console.log("Result:", intent1.intent);
if (intent1.intent === 'COMFORTING') console.log("✅ PASS");
else console.error("❌ FAIL");

// Test 2: High Anger -> Setting Boundary
console.log("\nTest 2: High Anger -> Setting Boundary");
mockState.emotions.sad = 0;
mockState.emotions.angry = 0.8;
const intent2 = neuralEngine.resolveSocialIntent(mockState, 1.0);
console.log("Result:", intent2.intent);
if (intent2.intent === 'SETTING_BOUNDARY') console.log("✅ PASS");
else console.error("❌ FAIL");

// Test 3: Teasing
console.log("\nTest 3: Happy + Arousal -> Teasing");
mockState.emotions.angry = 0;
mockState.emotions.happy = 0.8;
mockState.emotions.arousal = 0.8;
const intent3 = neuralEngine.resolveSocialIntent(mockState, 1.0);
console.log("Result:", intent3.intent);
if (intent3.intent === 'TEASING') console.log("✅ PASS");
else console.error("❌ FAIL");

// Test 4: Personality Evolution
console.log("\nTest 4: Personality Evolution");
const currentPersonality = { warmth: 0.5, energy: 0.5, assertiveness: 0.5, formality: 0.5 };
const stats = { avg_valence: 0.8, avg_arousal: 0.8, valence_volatility: 0.1 }; // High positive emotion
const newPersonality = neuralEngine.calculatePersonalityEvolution(currentPersonality, stats);
console.log("Old Warmth:", currentPersonality.warmth);
console.log("New Warmth:", newPersonality.warmth);

if (newPersonality.warmth > currentPersonality.warmth) console.log("✅ PASS (Warmth increased)");
else console.error("❌ FAIL");

console.log("\nTests Completed.");
