import { test } from "node:test";
import assert from "node:assert/strict";
import {
  detectVaultIntent,
  stripFromPrefix,
  snippet,
  hitHeading,
  mergeVaultEntries,
  extraHits,
  formatRuntimeReply,
  formatDeveloperReply,
} from "./src/systems/vaultSearch.js";

// ── detectVaultIntent ────────────────────────────────────────────────────────

test("detects runtime-details intent from natural language", () => {
  assert.equal(detectVaultIntent("what were your recent running details?"), "runtime");
  assert.equal(detectVaultIntent("show me your telemetry"), "runtime");
  assert.equal(detectVaultIntent("what have you been up to lately"), "runtime");
  assert.equal(detectVaultIntent("what's your uptime and memory right now"), "runtime");
  assert.equal(detectVaultIntent("Your Runtime Log please"), "runtime"); // case-insensitive
});

test("detects developer-vault intent", () => {
  assert.equal(detectVaultIntent("tell me about your codebase"), "developer");
  assert.equal(detectVaultIntent("how are you built?"), "developer");
  assert.equal(detectVaultIntent("show me your architecture notes"), "developer");
});

test("does not match casual conversation", () => {
  assert.equal(detectVaultIntent("how are you today?"), null);
  assert.equal(detectVaultIntent("hello!"), null);
  assert.equal(detectVaultIntent("tell me a story"), null);
  assert.equal(detectVaultIntent("I liked your recent idea"), null); // "your recent" too broad
  assert.equal(detectVaultIntent("what are you doing?"), null);
  assert.equal(detectVaultIntent(""), null);
  assert.equal(detectVaultIntent(null), null);
  assert.equal(detectVaultIntent(42), null);
});

// ── stripFromPrefix ──────────────────────────────────────────────────────────

test("strips the indexer From <path>: prefix", () => {
  assert.equal(stripFromPrefix("From Logs/2026-08-05.md:\n## Telemetry"), "## Telemetry");
  assert.equal(stripFromPrefix("plain text"), "plain text");
  assert.equal(stripFromPrefix(""), "");
});

test("snippet shows content, not the heading line", () => {
  assert.equal(
    snippet("From architecture.md:\n## Layers\nRAG + swarm pipeline"),
    "RAG + swarm pipeline"
  );
  assert.equal(snippet("plain body text"), "plain body text");
});

// ── hitHeading / merge / extra ───────────────────────────────────────────────

test("extracts heading from a semantic-search chunk", () => {
  assert.equal(
    hitHeading({ text: "From Logs/2026-08-05.md:\n## Telemetry — 14:40:35\n- CPU: 12%" }),
    "Telemetry — 14:40:35"
  );
  assert.equal(hitHeading({ text: "no heading here" }), "");
});

test("merges latest + hits, deduped by file+heading, latest first", () => {
  const latest = [
    { file: "2026-08-05.md", heading: "Telemetry — 14:40:35", text: "- CPU: 12%" },
    { file: "2026-08-05.md", heading: "Heartbeat — 14:32:22", text: "Uptime 99.9%" },
  ];
  const hits = [
    { source: "2026-08-05.md", text: "From 2026-08-05.md:\n## Telemetry — 14:40:35\n- CPU: 12%" },
    { source: "0-Inbox/notes.md", text: "From 0-Inbox/notes.md:\n## Maintenance\nreindexed" },
  ];
  const merged = mergeVaultEntries(latest, hits);
  assert.equal(merged.length, 3); // duplicate Telemetry hit dropped
  assert.equal(merged[0].heading, "Telemetry — 14:40:35"); // latest first
  assert.equal(merged[2].heading, "Maintenance");
  assert.equal(merged[2].file, "0-Inbox/notes.md");
});

test("headingless hits from the same source stay distinct", () => {
  const merged = mergeVaultEntries([], [
    { source: "notes.md", text: "From notes.md:\nfirst chunk body" },
    { source: "notes.md", text: "From notes.md:\nsecond chunk body" },
  ]);
  assert.equal(merged.length, 2); // no silent collapse
  assert.equal(merged[0].heading, "");
});

test("developer reply falls back for heading-only chunks", () => {
  const reply = formatDeveloperReply("architecture", {
    ok: true,
    hits: [{ source: "architecture.md", text: "From architecture.md:\n## Layers" }],
  });
  assert.ok(reply.includes("Layers")); // heading shown as the snippet
});

test("extraHits only returns hits not in latest", () => {
  const latest = [{ file: "2026-08-05.md", heading: "Telemetry — 14:40:35", text: "x" }];
  const hits = [
    { source: "2026-08-05.md", text: "## Telemetry — 14:40:35" },
    { source: "a.md", text: "## Other" },
  ];
  assert.deepEqual(extraHits(latest, hits), [hits[1]]);
});

// ── formatters ───────────────────────────────────────────────────────────────

test("runtime reply lists recent entries with headings and sources", () => {
  const reply = formatRuntimeReply("what were your recent running details?", {
    ok: true,
    latest: [
      { file: "2026-08-05.md", heading: "Telemetry — 14:40:35", text: "- CPU: 20.6%" },
      { file: "2026-08-05.md", heading: "Heartbeat — 14:32:22", text: "Uptime 99.9%" },
    ],
    hits: [],
  });
  assert.ok(reply.includes("Telemetry — 14:40:35"));
  assert.ok(reply.includes("- CPU: 20.6%"));
  assert.ok(reply.includes("2026-08-05.md"));
  assert.ok(!reply.includes("semantic search"));
});

test("runtime reply appends an 'also relevant' section for extra hits", () => {
  const reply = formatRuntimeReply("recent running details", {
    ok: true,
    latest: [{ file: "2026-08-05.md", heading: "Telemetry — 14:40:35", text: "- CPU: 12%" }],
    hits: [
      { source: "Logs/notes.md", text: "From Logs/notes.md:\n## Maintenance\nMemory reindexed 5185 chunks" },
    ],
  });
  assert.ok(reply.includes("Also relevant"));
  assert.ok(reply.includes("Memory reindexed"));
});

test("runtime reply handles offline brain", () => {
  const reply = formatRuntimeReply("running details", { ok: false, latest: [], hits: [] });
  assert.ok(reply.includes(":8000"));
  assert.ok(reply.includes("isn't responding"));
});

test("runtime reply handles an empty vault gracefully", () => {
  const reply = formatRuntimeReply("running details", { ok: true, latest: [], hits: [] });
  assert.ok(reply.includes("still quiet"));
});

test("developer reply formats semantic hits with sources", () => {
  const reply = formatDeveloperReply("your architecture", {
    ok: true,
    hits: [{ source: "architecture.md", text: "From architecture.md:\n## Layers\nRAG + swarm" }],
  });
  assert.ok(reply.includes("architecture.md"));
  assert.ok(reply.includes("RAG + swarm"));
});

test("developer reply handles offline and empty", () => {
  assert.ok(formatDeveloperReply("codebase", { ok: false }).includes(":8000"));
  assert.ok(formatDeveloperReply("codebase", { ok: true, hits: [] }).includes("didn't find"));
});
