import React from "react";

export default function PipelineGraph({ steps }) {
  if (!steps || steps.length === 0) return null;

  return (
    <div className="bg-black/30 backdrop-blur-md border border-white/10 p-4 rounded-xl h-full shadow-lg">
      <h3 className="text-white font-semibold mb-4 tracking-wider text-sm flex items-center">
        <span className="text-blue-400 mr-2">⚡</span> PIPELINE TELEMETRY
      </h3>
      <div className="space-y-3">
        {steps.map((s, i) => (
          <div key={i} className="flex flex-col relative group">
            <div className="flex justify-between items-center text-xs text-gray-300">
              <span className="capitalize">{s.name.replace(/_/g, ' ')}</span>
              <span className={`${s.latency > 1000 ? 'text-red-400' : 'text-green-400'} font-mono`}>
                {s.latency} ms
              </span>
            </div>
            {/* Visual connector line for all but last item */}
            {i !== steps.length - 1 && (
              <div className="absolute left-1/2 -bottom-3 h-3 w-px bg-white/20"></div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
