import React from "react";

export default function ChunkViewer({ chunks }) {
  if (!chunks || chunks.length === 0) {
    return (
      <div className="bg-black/30 backdrop-blur-md border border-white/10 p-4 rounded-xl shadow-lg flex items-center justify-center min-h-[200px]">
        <span className="text-gray-500 italic text-sm">No context chunks retrieved in this cycle.</span>
      </div>
    );
  }

  return (
    <div className="bg-black/30 backdrop-blur-md border border-white/10 p-4 rounded-xl shadow-lg max-h-[350px] overflow-y-auto custom-scrollbar">
      <h3 className="text-white font-semibold mb-4 tracking-wider text-sm sticky top-0 bg-black/80 backdrop-blur pb-2 z-10">
        <span className="text-green-400 mr-2">📚</span> RETRIEVED CONTEXT
      </h3>
      <div className="space-y-4">
        {chunks.map((c, i) => (
          <div key={i} className="bg-white/5 border border-white/10 p-3 rounded-lg hover:border-white/20 transition-colors">
            <div className="flex justify-between items-center mb-2">
              <div className="text-xs text-blue-300 font-mono truncate max-w-[70%]">
                {c.source.split('/').pop() || c.source}
              </div>
              <div className={`text-[10px] px-2 py-0.5 rounded-full ${c.score > 0.7 ? 'bg-green-500/20 text-green-300' : 'bg-yellow-500/20 text-yellow-300'}`}>
                Score: {c.score.toFixed(2)}
              </div>
            </div>
            <div className="text-sm text-gray-300 leading-relaxed wrap-break-word">
              {c.text ? c.text.substring(0, 150) + (c.text.length > 150 ? "..." : "") : "No text"}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
