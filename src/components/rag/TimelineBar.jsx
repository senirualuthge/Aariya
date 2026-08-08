import React from "react";

export default function TimelineBar({ steps }) {
  if (!steps || steps.length === 0) return null;

  const total = steps.reduce((a, s) => a + s.latency, 0) || 1; // avoid / 0

  return (
    <div className="bg-black/30 backdrop-blur-md border border-white/10 p-4 rounded-xl shadow-lg">
      <div className="flex justify-between text-xs text-gray-400 mb-2">
        <span>Timeline Trace</span>
        <span>{total.toFixed(0)} ms total</span>
      </div>
      <div className="flex h-3 rounded-full overflow-hidden border border-white/5 bg-gray-900">
        {steps.map((s, i) => {
          const w = (s.latency / total) * 100;
          // color stagger
          const colors = ['bg-blue-500', 'bg-purple-500', 'bg-cyan-500', 'bg-indigo-500', 'bg-teal-500'];
          const colorClass = colors[i % colors.length];

          return (
            <div
              key={i}
              style={{ width: `${Math.max(w, 2)}%` }}
              className={`${colorClass} relative group transition-all duration-300 hover:brightness-125`}
              title={`${s.name}: ${s.latency}ms`}
            />
          );
        })}
      </div>
      <div className="flex justify-between mt-2 flex-wrap gap-2">
        {steps.map((s, i) => {
          const colors = ['text-blue-400', 'text-purple-400', 'text-cyan-400', 'text-indigo-400', 'text-teal-400'];
          const colorClass = colors[i % colors.length];
          return (
            <div key={i} className={`text-[10px] ${colorClass} capitalize flex items-center`}>
              <span className="w-2 h-2 rounded-full bg-current mr-1"></span>
              {s.name.replace(/_/g, ' ')}
            </div>
          );
        })}
      </div>
    </div>
  );
}
