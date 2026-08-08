/**
 * SearchSystem.js
 * Handles "Internet Surfing" capabilities.
 *
 * Real searches are routed through the Aariya brain server's /api/web-search
 * endpoint, which fans out to the configured provider (Bing → SerpAPI →
 * Serper.dev → mock) so API keys never leave the backend. If the brain server
 * is unreachable but a VITE_SERPER_API_KEY is set, the browser calls
 * Serper.dev directly as a fallback. When neither path yields real results we
 * drop back to the local simulated knowledge base so the demo always answers.
 */

import { connectivityManager } from './ConnectivityManager';

// Backend brain server — same convention as NewsPanel (`http://<host>:8000/api/...`).
const BRAIN_API = `http://${window.location.hostname}:8000`;

const SERPER_ENDPOINT = 'https://google.serper.dev/search';
const MAX_RESULTS = 5;
const TIMEOUT_MS = 12000;

// Mock database for "Simulated Internet"
const KNOWLEDGE_BASE = {
    "current events": [
        "Global climate summit reaches new carbon reduction agreement.",
        "SpaceX successfully launches Starship v3 for Mars cargo test.",
        "New AI model breaks barrier in solving mathematical theorems."
    ],
    "news": [
        "Tech stocks rally as interest rates stabilize.",
        "Local cat elected mayor of historic village in novelty election.",
        "Breakthrough in fusion energy announced by European researchers."
    ],
    "weather": "It looks like it's sunny with a chance of digital clouds.",
    "time": () => `The current local time is ${new Date().toLocaleTimeString()}.`,
    "date": () => `Today is ${new Date().toLocaleDateString()}.`
};

class SearchSystem {
    constructor() {
        // Optional client-side Serper key — only used as a direct-call fallback
        // when the brain server (which holds the server-side keys) is down.
        // NOTE: this ships into the browser bundle, so it is for LOCAL DEV ONLY.
        // Prefer setting SERPER_API_KEY in the backend .env instead.
        this.apiKey = import.meta.env.VITE_SERPER_API_KEY || null;
        this.searchHistory = [];
    }

    /**
     * Performs a web search (or simulation).
     * @param {string} query - The search term.
     */
    async search(query) {
        if (!connectivityManager.isOnline) {
            return {
                success: false,
                source: "system",
                content: "I'm currently offline and can't check the web."
            };
        }

        console.log(`[SearchSystem] Browsing for: "${query}"...`);

        // 1. Try a real web search (backend first, direct Serper as fallback).
        const real = await this.performRealSearch(query);
        if (real.success) return real;

        // 2. Fallback to the local simulated knowledge base.
        return await this.performSimulatedSearch(query);
    }

    /**
     * Real web search.
     * 1. Preferred: /api/web-search on the brain server (keys stay server-side,
     *    works with Bing / SerpAPI / Serper depending on what is configured).
     * 2. Fallback: direct Serper.dev call when a VITE_SERPER_API_KEY is set.
     *
     * Returns { success, source, content, results? } — success:false means the
     * caller should fall back to the simulated search.
     */
    async performRealSearch(query) {
        // 1. Route through the brain server.
        const backend = await this.searchViaBackend(query);
        if (backend.success) return backend;

        // 2. Direct Serper.dev call (client-side key configured).
        if (this.apiKey) {
            const direct = await this.searchViaSerper(query);
            if (direct.success) return direct;
        }

        // 3. Neither worked — let the caller fall back to simulated results.
        return { success: false, error: backend.error || "Web search unavailable" };
    }

    async searchViaBackend(query) {
        try {
            const res = await fetch(
                `${BRAIN_API}/api/web-search?q=${encodeURIComponent(query)}&num=${MAX_RESULTS}`,
                { signal: AbortSignal.timeout(TIMEOUT_MS) }
            );
            if (!res.ok) throw new Error(`Search API ${res.status}`);
            const json = await res.json();

            // A "mock" provider means no real key is configured server-side —
            // treat as not-real so we fall through to the simulated results.
            if (json.provider === 'mock' || !json.results || !json.results.length) {
                return { success: false, error: 'Backend has no search provider configured' };
            }

            return this._formatResults(query, json.results, `brain:${json.provider}`);
        } catch (e) {
            console.warn('[SearchSystem] Backend search unavailable:', e.message);
            return { success: false, error: e.message };
        }
    }

    async searchViaSerper(query) {
        try {
            const res = await fetch(SERPER_ENDPOINT, {
                method: 'POST',
                headers: { 'X-API-KEY': this.apiKey, 'Content-Type': 'application/json' },
                body: JSON.stringify({ q: query, num: MAX_RESULTS }),
                signal: AbortSignal.timeout(TIMEOUT_MS),
            });
            if (!res.ok) throw new Error(`Serper ${res.status}`);
            const json = await res.json();
            const results = (json.organic || []).slice(0, MAX_RESULTS);
            if (!results.length) return { success: false, error: 'No organic results' };

            return this._formatResults(query, results, 'serper');
        } catch (e) {
            console.warn('[SearchSystem] Direct Serper search failed:', e.message);
            return { success: false, error: e.message };
        }
    }

    /**
     * Turn raw search results into a readable "readout" for the AI's reply.
     * @param {string} query
     * @param {Array} results - items with {title, url|link, snippet|description}
     * @param {string} source  - e.g. 'brain:serper' | 'serper'
     */
    _formatResults(query, results, source) {
        const lines = results.map((r, i) => {
            const title = r.title || 'Untitled';
            const snippet = r.snippet || r.description || '';
            const url = r.url || r.link || '';
            return `${i + 1}. ${title} — ${snippet}${url ? ` (${url})` : ''}`;
        });

        const content = `Here's what I found about "${query}":\n${lines.join('\n')}`;
        this.searchHistory.push({ query, result: content, timestamp: Date.now() });

        return { success: true, source, results, content };
    }

    async performSimulatedSearch(query) {
        // Simulate network delay
        await new Promise(resolve => setTimeout(resolve, 1500));

        const lowerQuery = query.toLowerCase();
        let result = "I searched the web, but I couldn't find a specific answer to that yet.";

        // Basic Keyword Matching for Simulation
        if (lowerQuery.includes("time")) {
            result = KNOWLEDGE_BASE.time();
        } 
        else if (lowerQuery.includes("date") || lowerQuery.includes("day")) {
            result = KNOWLEDGE_BASE.date();
        }
        else if (lowerQuery.includes("weather")) {
            result = KNOWLEDGE_BASE.weather;
        }
        else if (lowerQuery.includes("news") || lowerQuery.includes("headline")) {
            const news = KNOWLEDGE_BASE.news;
            result = "Here are some headlines I found: " + news.join(" | ");
        }
        else if (lowerQuery.includes("event") || lowerQuery.includes("happening")) {
            const events = KNOWLEDGE_BASE["current events"];
            result = "Searching current events... Found these: " + events.join(" | ");
        }
        else if (lowerQuery.includes("who is")) {
             result = `Search Result: ${query.replace("who is", "").trim()} is a notable figure or entity, but my offline database is limited on specific biographies right now.`;
        }
        else if (lowerQuery.includes("what is")) {
             result = `Search Result: Definition for ${query.replace("what is", "").trim()} found. It is generally defined as a concept or object relevant to your query.`;
        }

        this.searchHistory.push({ query, result, timestamp: Date.now() });

        return {
            success: true,
            source: "simulated_web",
            content: result
        };
    }
}

export const searchSystem = new SearchSystem();
