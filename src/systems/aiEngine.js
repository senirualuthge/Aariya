// aiEngine.js - Enhanced with Dynamic Dialogue Generator
import { AARIYA_PERSONALITY } from './prompts/personality.js';
import { DialogueGenerator } from './DialogueGenerator.js';
import { sentimentAnalyzer } from './SentimentAnalyzer.js';
import { memoryManager } from './memory/MemoryManager.js';
import { advancedMemory } from './memory/AdvancedMemoryManager.js'; // NEW
import { contextManager } from './memory/ContextManager.js';
import { searchSystem } from './internet/SearchSystem.js';
import { habitManager } from './lifestyle/HabitManager.js';
import { detectVaultIntent, fetchVaultNotes, formatRuntimeReply, formatDeveloperReply } from './vaultSearch.js';
import { brainClient } from './brainClient.js';

const generator = new DialogueGenerator('aria');

/**
 * Analyzes the user's input to detect basic and advanced emotions.
 */
export async function analyzeUserEmotion(input) {
    const analysis = await sentimentAnalyzer.analyze(input);
    
    return { 
        detected: analysis.primaryEmotion !== 'neutral', 
        emotion: analysis.primaryEmotion,
        score: analysis.score,
        magnitude: analysis.magnitude
    };
}

/**
 * Handles a message from the user by generating a dynamic response.
 *
 * Primary path: the backend BrainV2 (identity, memory, emotion, personality,
 * inner monologue) over the shared WebSocket. If the brain connection isn't
 * ready (server down / not yet booted), falls back to the browser generator.
 *
 * @param {string} userId
 * @param {string} input
 * @param {object} opts  { onChunk(streamedText, lastToken) } — live-token feed
 */
export async function handleMessage(userId, input, opts = {}) {
    const { onChunk } = opts || {};

    // 1. Preferred path — Aariya's actual cognition (memory, emotion, persona,
    //    inner monologue all live server-side). Her replies stream in real time.
    //    brainClient.send rejects immediately when the socket isn't connected,
    //    so a not-yet-ready server cleanly drops to the local fallback.
    try {
        const brain = await brainClient.send(input, { onChunk });
        if (brain && brain.text) {
            return {
                text: brain.text,
                memory: {
                    profile: {
                        name: "User",
                        intimacyLevel: 2,
                        accent: 'neutral',
                    },
                    thought: brain.thought || null,
                },
            };
        }
    } catch (brainErr) {
        console.warn('[AI Engine] Brain unreachable, falling back to local generator:', brainErr.message);
    }

    // 2. Fallback path — browser-only generation (used when the brain server
    //    is offline). Mirrors the original behaviour below.
    // 1. Analyze Emotion & Store user message in memory
    const emotionAnalysis = await analyzeUserEmotion(input);
    
    // Legacy Memory
    await memoryManager.store({ role: 'user', content: input }, 'short');
    
    // Advanced Memory (STM/MTM Update)
    advancedMemory.addInteraction('user', input, { 
        emotion: emotionAnalysis.emotion,
        score: emotionAnalysis.score 
    });

    // 2. Add to context manager for summarization control & Memory Context Window
    await contextManager.addMessage({ role: 'user', content: input });
    memoryManager.addToContext('user', input);

    // Context for Debug
    // const currentContext = advancedMemory.getRecentContext(); // Switch to advanced context later
    const currentContext = memoryManager.getContext();
    console.log(`[AI Engine] Context Topic: ${currentContext.topic}`);

    // 3. Check for Search Intent & Generate Response
    let text = "";
    
    // 3a. Obsidian vault search — runtime-details / codebase questions are
    // answered directly from Aariya's vault notes (brain server /api/obsidian/*).
    // Checked before the generic intent map so "how are you running lately?"
    // surfaces running details instead of a wellbeing response.
    const vaultIntent = detectVaultIntent(input);
    if (vaultIntent) {
        const payload = await fetchVaultNotes(input, vaultIntent);
        text = vaultIntent === 'runtime'
            ? formatRuntimeReply(input, payload)
            : formatDeveloperReply(input, payload);
    } else {
        // Quick intent check
        const intent = generator.detectIntent(input);
        
        if (intent === 'information') {
            // --- INTERNET SEARCH INTEGRATION ---
            const searchResult = await searchSystem.search(input);
            if (searchResult.success) {
                // Use specialized knowledge blocks
                const opener = generator.getRandomBlock('knowledge').opener || "I found this:"; // Fallback
                // Construct a "readout" style response
                text = `${opener} ${searchResult.content}`;
            } else {
                text = "I tried to connect to the net, but I'm offline right now.";
            }
        } else {
            // Standard Conversation
            // NEW: Retrieve relevant memory context
            const retrievedContext = advancedMemory.retrieveContext(input);
            if (retrievedContext.length > 0) {
                console.log(`[AI Engine] Retrieved Context:`, retrievedContext.map(m => m.content));
            }

            // HABIT CONTEXT INJECTION
            const habitContext = await habitManager.getContextString();
            
            text = await generator.generateResponse(input, retrievedContext, habitContext);
        }
    }

    // 4. Store bot response in memory and context
    await memoryManager.store({ role: 'assistant', content: text }, 'long');
    
    // Advanced Memory Update (AI)
    advancedMemory.addInteraction('ai', text, { emotion: 'neutral' }); // ToDo: Track AI emotion state too
    
    await contextManager.addMessage({ role: 'assistant', content: text });
    memoryManager.addToContext('assistant', text);

    // Mock memory object for UI compatibility
    const memory = {
        profile: {
            name: "User",
            intimacyLevel: 2,
            accent: 'neutral'
        }
    };

    return { text, memory };
}

/**
 * Updates the generator's personality. Useful for syncing with the store.
 */
export function setGeneratorPersonality(personality) {
    generator.setPersonality(personality);
}

export { AARIYA_PERSONALITY };
