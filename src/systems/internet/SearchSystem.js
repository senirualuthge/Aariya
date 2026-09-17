/**
 * SearchSystem.js
 * Handles "Internet Surfing" capabilities.
 *
 * Real searches are routed through the Aariya brain server's /api/web-search
 * endpoint, which fans out to the configured provider (Bing → SerpAPI →
 * Serper.dev → DuckDuckGo → Wikipedia) so API keys never leave the backend.
 * If the brain server is unreachable but a VITE_SERPER_API_KEY is set, the
 * browser calls Serper.dev directly as a fallback. There is NO simulated
 * knowledge base: when no real provider answers, search() returns
 * success:false and callers show an honest "couldn't search" message. Only
 * genuinely local facts (the user's actual clock) are answerable offline.
 */

import { connectivityManager } from './ConnectivityManager';

import { apiBase } from '../../utils/apiHost';

const BRAIN_API = apiBase();

const SERPER_ENDPOINT = 'https://google.serper.dev/search';
const MAX_RESULTS = 5;
const TIMEOUT_MS = 12000;

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
     * Performs a web search; falls back to honest offline answers.
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

        // 2. Only genuinely local facts (the real system clock) are
        //    answerable offline; everything else stays honestly unanswered.
        return this.performLocalRealtimeSearch(query);
    }

    /**
     * Real web search.
     * 1. Preferred: /api/web-search on the brain server (keys stay server-side,
     *    works with Bing / SerpAPI / Serper depending on what is configured).
     * 2. Fallback: direct Serper.dev call when a VITE_SERPER_API_KEY is set.
     *
     * Returns { success, source, content, results? } — success:false means the
     * caller should fall back to the honest offline path.
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

        // 3. Neither worked — report honestly; no results are fabricated.
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

            // No usable provider/results server-side → fall through to the
            // honest local path below.
            if (!json.provider || json.provider === 'mock' ||
                !json.results || !json.results.length) {
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

    performLocalRealtimeSearch(query) {
        // The only offline truths available in a browser are its own clock.
        const lowerQuery = query.toLowerCase();

        if (lowerQuery.includes("time") && !lowerQuery.includes("times")) {
            const content = `The current local time is ${new Date().toLocaleTimeString()}.`;
            this.searchHistory.push({ query, result: content, timestamp: Date.now() });
            return { success: true, source: "local_clock", content };
        }
        if (lowerQuery.includes("date") || lowerQuery.includes("what day")) {
            const content = `Today is ${new Date().toLocaleDateString()}.`;
            this.searchHistory.push({ query, result: content, timestamp: Date.now() });
            return { success: true, source: "local_clock", content };
        }

        // No fabricated headlines/definitions — report honestly instead.
        return {
            success: false,
            source: "none",
            error: "No search provider reachable and no local answer exists",
        };
    }
}

export const searchSystem = new SearchSystem();
