import React from "react";
import { parseVaultContext } from "../../utils/vaultContext.js";

const ACCENTS = {
  developer: {
    dot: "bg-cyan-400",
    badge: "bg-cyan-500/20 text-cyan-300 border-cyan-500/40",
    hover: "hover:border-cyan-500/30",
  },
  runtime: {
    dot: "bg-purple-400",
    badge: "bg-purple-500/20 text-purple-300 border-purple-500/40",
    hover: "hover:border-purple-500/30",
  },
};

export default function VaultContextPanel({ raw }) {
  const blocks = parseVaultContext(raw);

  if (blocks.length === 0) {
    return (
      <div className="bg-black/30 backdrop-blur-md border border-white/10 p-4 rounded-xl shadow-lg flex items-center justify-center min-h-[120px]">
        <span className="text-gray-500 italic text-sm">
          No Obsidian vault context pulled this cycle.
        </span>
      </div>
    );
  }

  return (
    <div className="bg-black/30 backdrop-blur-md border border-white/10 p-4 rounded-xl shadow-lg">
      <h3 className="text-white font-semibold mb-4 tracking-wider text-sm">
        <span className="text-cyan-400 mr-2">🗂️</span> OBSIDIAN VAULT CONTEXT
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {blocks.map((block) => {
          const a = ACCENTS[block.kind] || ACCENTS.developer;
          return (
            <div
              key={block.kind}
              className={`bg-white/5 border border-white/10 p-3 rounded-lg ${a.hover} transition-colors`}
            >
              <div className="flex items-center gap-2 mb-3">
                <span className={`w-2 h-2 rounded-full ${a.dot}`} />
                <span
                  className={`text-[10px] px-2 py-0.5 rounded-full tracking-wider uppercase border ${a.badge}`}
                >
                  {block.label}
                </span>
              </div>
              {block.entries.length === 0 ? (
                <div className="text-xs text-gray-500 italic">No matching notes.</div>
              ) : (
                <div className="space-y-3">
                  {block.entries.map((entry, i) => (
                    <div key={i} className="border-l-2 border-white/10 pl-2">
                      <div
                        className="text-[10px] text-blue-300 font-mono truncate mb-1"
                        title={entry.source}
                      >
                        {entry.source.split("/").pop() || entry.source}
                      </div>
                      <div className="text-xs text-gray-300 leading-relaxed whitespace-pre-wrap break-words">
                        {entry.text.substring(0, 160)}
                        {entry.text.length > 160 ? "..." : ""}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
