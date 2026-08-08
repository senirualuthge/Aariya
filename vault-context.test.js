import { test } from "node:test";
import assert from "node:assert/strict";
import { parseVaultContext } from "./src/utils/vaultContext.js";

const SAMPLE = `[Codebase context — developer Obsidian vault:]
[Obsidian vault context:]
- (0-Inbox/New RAG Visualization DashB.md) From 0-Inbox/New RAG Visualization DashB.md:
ServerOutput.meta["rag"] = rag_trace
- (architecture.md) From architecture.md: single line note
[Running details — runtime Obsidian vault:]
[Obsidian vault context:]
- (Logs/2026-08-05.md) From Logs/2026-08-05.md:
## Telemetry — 14:40:35
- Server uptime: 0s
- Active agents: 16`;

test("parses both vault blocks with roles", () => {
  const blocks = parseVaultContext(SAMPLE);
  assert.equal(blocks.length, 2);
  assert.equal(blocks[0].kind, "developer");
  assert.equal(blocks[0].label, "Developer vault · Codebase context");
  assert.equal(blocks[1].kind, "runtime");
  assert.equal(blocks[1].label, "Runtime vault · Running details");
});

test("parses entries with sources", () => {
  const blocks = parseVaultContext(SAMPLE);
  assert.equal(blocks[0].entries.length, 2);
  assert.deepEqual(blocks[0].entries[0].source, "0-Inbox/New RAG Visualization DashB.md");
  assert.deepEqual(blocks[0].entries[1].source, "architecture.md");
  assert.equal(blocks[1].entries.length, 1);
  assert.deepEqual(blocks[1].entries[0].source, "Logs/2026-08-05.md");
});

test("preserves multi-line entry text", () => {
  const blocks = parseVaultContext(SAMPLE);
  const telemetry = blocks[1].entries[0].text;
  assert.ok(telemetry.includes("## Telemetry — 14:40:35"));
  assert.ok(telemetry.includes("Active agents: 16"));
});

test("returns [] for missing / empty / non-string input", () => {
  assert.deepEqual(parseVaultContext(undefined), []);
  assert.deepEqual(parseVaultContext(""), []);
  assert.deepEqual(parseVaultContext(null), []);
  assert.deepEqual(parseVaultContext(42), []);
});

test("skips unknown / unlabeled blocks", () => {
  const blocks = parseVaultContext(
    "[Something else entirely:]\n[Obsidian vault context:]\n- (x.md) From x.md: text"
  );
  assert.deepEqual(blocks, []);
});

test("handles a developer-only string", () => {
  const blocks = parseVaultContext(
    "[Codebase context — developer Obsidian vault:]\n[Obsidian vault context:]\n- (a.md) From a.md: hello"
  );
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].kind, "developer");
  assert.equal(blocks[0].entries[0].text, "hello");
});
