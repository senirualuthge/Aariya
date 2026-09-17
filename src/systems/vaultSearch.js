// vaultSearch.js — make Aariya's Obsidian vault notes searchable from the chat UI.
//
// The chat engine (aiEngine.js) is fully client-side, so when the user asks a
// question about Aariya's running details ("what were your recent running
// details?") or her codebase, we hit the brain server's /api/obsidian/*
// endpoints and compose a reply from the notes themselves.
//
// Pure helpers (intent detection, reply formatting) are kept separate from the
// fetch glue so they're unit-testable with `node --test`.

function _apiBase() {
  return brainBaseUrl();
}

import { apiBase } from '../utils/apiHost.js';

function brainBaseUrl() {
  return apiBase();
}

// Phrases that mean "tell me how you've been running" → runtime vault
// (telemetry, research turns, maintenance notes).
const RUNTIME_PHRASES = [
  "running details",
  "runtime details",
  "runtime log",
  "runtime vault",
  "recent running",
  "recent activity",
  "recent notes",
  "what have you been doing",
  "what have you been up to",
  "how are you running",
  "how is it running",
  "how has it been running",
  "your telemetry",
  "telemetry",
  "your uptime",
  "uptime",
  "your logs",
  "system status",
  "what happened recently",
  "what did you do recently",
];

// Phrases that mean "tell me about your code / architecture" → developer vault.
const DEVELOPER_PHRASES = [
  "developer vault",
  "codebase",
  "your architecture",
  "your source code",
  "your source",
  "how do you work",
  "how are you built",
  "your code",
  "your docs",
  "developer notes",
  "architecture notes",
];

/**
 * Detect whether the user is asking about one of the Obsidian vaults.
 * Returns 'runtime' | 'developer' | null.
 */
export function detectVaultIntent(input) {
  if (!input || typeof input !== "string") return null;
  const lower = input.toLowerCase();
  if (RUNTIME_PHRASES.some((p) => lower.includes(p))) return "runtime";
  if (DEVELOPER_PHRASES.some((p) => lower.includes(p))) return "developer";
  return null;
}

/**
 * Strip the indexer's redundant "From <path>:\n" prefix from a chunk.
 */
export function stripFromPrefix(text) {
  if (!text) return "";
  return text.replace(/^From\s+[^:\n]+:\s*\n?/, "").trim();
}

/**
 * First meaningful line of a chunk for compact list entries: drops the
 * "From <path>:" prefix and any `## Heading` line, then takes the first line.
 */
export function snippet(text, max = 160) {
  const s = stripFromPrefix(text).replace(/^#{1,6}\s+.*$/m, "").trim();
  return s.split("\n")[0].slice(0, max);
}

/**
 * Fetch vault notes from the brain server. Never throws — returns
 * { ok, latest, hits } so the caller always has something to format.
 *   runtime:   latest = newest Logs/ entries, hits = semantic matches
 *   developer: hits = semantic matches across the developer vault
 */
export async function fetchVaultNotes(input, intent) {
  const base = brainBaseUrl();
  try {
    if (intent === "runtime") {
      const [latestRes, searchRes] = await Promise.all([
        fetch(`${base}/api/obsidian/runtime/latest?limit=8`),
        fetch(`${base}/api/obsidian/search?q=${encodeURIComponent(input)}&vault=runtime&k=5`),
      ]);
      const latest = latestRes.ok ? (await latestRes.json()).entries || [] : [];
      const search = searchRes.ok ? (await searchRes.json()).hits || [] : [];
      return { ok: true, latest, hits: search };
    }
    const searchRes = await fetch(
      `${base}/api/obsidian/search?q=${encodeURIComponent(input)}&vault=developer&k=5`
    );
    const hits = searchRes.ok ? (await searchRes.json()).hits || [] : [];
    return { ok: true, latest: [], hits };
  } catch {
    return { ok: false, latest: [], hits: [] };
  }
}

/**
 * Extract the `## <Heading>` from a semantic-search chunk (hits come back as
 * `From <path>:\n## Heading…` documents, unlike `latest` entries which are
 * already structured). Returns "" when the chunk has no heading.
 */
export function hitHeading(hit) {
  const m = hit?.text?.match(/^##\s+(.+)$/m);
  return m ? m[1].trim() : "";
}

/**
 * Merge latest entries + search hits into one display list — latest (recency)
 * first, then semantic hits — deduped by (file + heading) so a hit already
 * shown in "latest" isn't repeated.
 */
export function mergeVaultEntries(latest = [], hits = []) {
  const seen = new Set();
  const merged = [];
  for (const e of latest) {
    const key = `${e.file}::${e.heading}`;
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(e);
  }
  for (const h of hits) {
    // Headingless chunks (e.g. developer-notes without ## sections) would all
    // share the key `source::` and collapse into one entry — include a text
    // slice so distinct chunks from the same file stay distinct.
    const heading = hitHeading(h);
    const key = `${h.source}::${heading || h.text?.slice(0, 60) || ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push({ file: h.source, heading, text: h.text });
  }
  return merged;
}

/**
 * Semantic hits not already represented in the recency list (by file+heading).
 */
export function extraHits(latest = [], hits = []) {
  return hits.filter((h) => !latest.some((l) => l.heading === hitHeading(h)));
}

function formatEntry(e) {
  const file = e.file || e.source || "";
  const heading = e.heading ? `**${file ? `${file} · ` : ""}${e.heading}**` : `**${file}**`;
  const body = e.text ? stripFromPrefix(e.text) : "";
  const sourceLine = file ? `_— ${file}_` : "";
  return `${heading}\n${body}\n${sourceLine}`.trim();
}

/**
 * Compose the chat reply for a runtime-details question.
 * Returns a string (never null) so the caller always has something to say.
 */
export function formatRuntimeReply(query, { ok, latest = [], hits = [] } = {}) {
  if (ok === false) {
    return `I couldn't reach my runtime vault right now — the brain server at ${_apiBase()} isn't responding. Try again once it's up. 🤖`;
  }
  const entries = mergeVaultEntries(latest, hits);
  if (entries.length === 0) {
    return "My runtime vault is still quiet — no running details logged yet. As I run, I record telemetry, research turns and maintenance notes there, and you'll be able to ask about them. 📓";
  }

  const lines = ["Here's what's in my runtime vault lately — 📓", ""];
  for (const e of entries.slice(0, 8)) {
    lines.push(formatEntry(e), "");
  }
  const extras = extraHits(latest, hits);
  if (extras.length > 0) {
    lines.push(`Also relevant to *"${query}"* via semantic search — 🔎`, "");
    for (const h of extras.slice(0, 3)) {
      lines.push(`- (${h.source || "?"}) ${snippet(h.text, 140)}`);
    }
  }
  return lines.join("\n").trim();
}

/**
 * Compose the chat reply for a codebase / architecture question.
 */
export function formatDeveloperReply(query, { ok, hits = [] } = {}) {
  if (ok === false) {
    return `I couldn't reach my developer vault right now — the brain server at ${_apiBase()} isn't responding. Try again once it's up. 🤖`;
  }
  if (hits.length === 0) {
    return "I didn't find matching notes in my developer vault for that. Try asking about my architecture, RAG pipeline or agents. 📚";
  }
  const lines = ["Here's what I found in my developer vault (codebase notes) — 📚", ""];
  for (const h of hits.slice(0, 5)) {
    // Fall back to the heading (or the source file) when a chunk is
    // heading-only and has no body text to show.
    const s = snippet(h.text) || hitHeading(h) || h.source || "…";
    lines.push(`- (${h.source || "?"}) ${s}`);
  }
  lines.push("", `_Semantic matches for "${query}"_`);
  return lines.join("\n").trim();
}
