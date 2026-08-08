/**
 * vaultContext.js
 * ───────────────
 * Parses the `obsidian_vault_context` string that the research agent stores in
 * its RAG trace. The string is produced by WebIntelligenceAgent._gather_vault_context
 * (server/systems/agent/controller.py) and has the shape:
 *
 *   [Codebase context — developer Obsidian vault:]
 *   [Obsidian vault context:]
 *   - (source/path.md) From source/path.md: text...
 *   - (source2.md) From source2.md: multiline
 *     text continues here
 *   [Running details — runtime Obsidian vault:]
 *   [Obsidian vault context:]
 *   - (Logs/2026-08-05.md) From Logs/2026-08-05.md: ...
 *
 * Returns an array of blocks: [{ kind, label, entries: [{ source, text }] }].
 * Pure and dependency-free so it can be unit-tested in plain Node.
 */

export function parseVaultContext(raw) {
  if (!raw || typeof raw !== "string") return [];

  const blocks = [];
  // Split only at role headers (any header containing "developer" or
  // "runtime") — NOT at the nested "[Obsidian vault context:]" label, which
  // belongs to the block that precedes it. Matching on the role keywords keeps
  // the parser robust to label wording changes in the producer.
  const rawBlocks = raw.split(/\n(?=\[[^\]]*(?:developer|runtime)[^\]]*\])/).filter((b) => b.trim());

  for (const rawBlock of rawBlocks) {
    const headerMatch = rawBlock.match(/^\[([^\]]+)\]/);
    if (!headerMatch) continue;

    const header = headerMatch[1];
    const isDeveloper = /developer/i.test(header);
    const isRuntime = /runtime/i.test(header);
    if (!isDeveloper && !isRuntime) continue; // skip unknown labels

    // Entries start with "- ("; each entry's text continues until the next
    // "- (" line (chunk text embeds newlines, e.g. markdown bodies).
    const lines = rawBlock.slice(headerMatch[0].length).split("\n");
    const entries = [];
    for (let i = 0; i < lines.length; i++) {
      const m = lines[i].match(/^-\s*\(([^)]+)\)\s*(.*)$/);
      if (!m) continue;
      // The producer prefixes each entry with "From <path>:" — the source is
      // already surfaced separately by the UI, so strip the redundant prefix.
      const text = [m[2].replace(/^From\s+[^:]+:\s*/, "")];
      let j = i + 1;
      while (j < lines.length && !/^-\s*\(/.test(lines[j])) {
        text.push(lines[j]);
        j += 1;
      }
      entries.push({ source: m[1], text: text.join("\n").replace(/^\n+/, "") });
      i = j - 1;
    }

    blocks.push({
      kind: isDeveloper ? "developer" : "runtime",
      label: isDeveloper
        ? "Developer vault · Codebase context"
        : "Runtime vault · Running details",
      entries,
    });
  }

  return blocks;
}
