// DialogueGenerator.js - Dynamic, personality-aware sentence assembly engine
import OpenAI from 'openai';
import { AARIYA_PERSONALITY, GASLIGHT_PERSONALITY } from './prompts/personality.js';

// Kept for legacy compatibility with aiEngine.js (search openers)
const THOUGHT_BLOCKS = {
    knowledge: {
        opener: "I found this info:",
        transitions: [],
        closers: []
    },
    // Fallbacks for safety
    aria: { opener: "...", closers: [] }, 
    calm: { opener: "...", closers: [] }
};

const INTENT_MAP = {
    greeting: ["hello", "hi", "hey", "greetings"],
    wellbeing: ["how are you", "how's it going", "how are you doing"],
    existence: ["who are you", "what are you", "your name"],
    emotional: ["sad", "happy", "tired", "stressed", "worried", "love", "hate"],
    action: ["dance", "spin", "move", "closer", "stop"],
    information: ["search", "find", "who is", "what is", "news", "weather", "time", "date", "event"]
};

export class DialogueGenerator {
    constructor(personality = 'aria') {
        this.personality = personality;
        this.history = [];
        this.apiKey = import.meta.env.VITE_OPENAI_API_KEY;
        this.baseURL = import.meta.env.VITE_OPENAI_BASE_URL;
        this.model = import.meta.env.VITE_LLM_MODEL || 'gpt-3.5-turbo';

        if (this.apiKey) {
            this.openai = new OpenAI({
                apiKey: this.apiKey,
                baseURL: this.baseURL,
                dangerouslyAllowBrowser: true // Required for frontend use
            });
        } else {
            console.warn('[DialogueGenerator] No OpenAI API Key found. Chat will not function correctly.');
        }
    }

    setPersonality(personality) {
        this.personality = personality;
    }

    /**
     * Finds the primary intent of the user message.
     * Kept for compatibility with aiEngine.js
     */
    detectIntent(input) {
        const lower = input.toLowerCase();
        for (const [intent, keywords] of Object.entries(INTENT_MAP)) {
            if (keywords.some(k => lower.includes(k))) return intent;
        }
        return 'general';
    }

    /**
     * Legacy support for aiEngine.js search block opener
     */
    getRandomBlock(type) {
        // Return a mock block structure expected by aiEngine
        return (THOUGHT_BLOCKS[type] || THOUGHT_BLOCKS.knowledge) || { opener: "Here is what I found:" };
    }

    /**
     * Assembles a dynamic response based on input and active personality using LLM.
     * @param {string} input - User message
     * @param {Array} context - Retrieved memories (optional)
     */
    async generateResponse(input, context = [], extraContext = "") {
        if (!this.openai) {
            return "I'm having trouble connecting to my thought process right now. (Missing API Key)";
        }

        try {
            // Construct context string
            const memoryContext = context.length > 0 
                ? `\nRelevant Memories:\n${context.map(m => `- ${m.content}`).join('\n')}`
                : "";

            const systemPrompt = this.personality === 'gaslight' ? GASLIGHT_PERSONALITY : AARIYA_PERSONALITY;

            const messages = [
                { role: "system", content: systemPrompt + memoryContext + extraContext },
                ...this.history.slice(-10), // Keep last 10 turns for immediate context
                { role: "user", content: input }
            ];

            const completion = await this.openai.chat.completions.create({
                messages: messages,
                model: this.model,
            });

            const reply = completion.choices[0].message.content;

            // Update history
            this.history.push({ role: "user", content: input });
            this.history.push({ role: "assistant", content: reply });
            if (this.history.length > 20) this.history = this.history.slice(-20);

            return reply;

        } catch (error) {
            console.error('[DialogueGenerator] LLM Error:', error);
            return "I... I lost my train of thought for a moment. (API Error)";
        }
    }
}
