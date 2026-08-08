import React from "react";

export default function MetricsPanel({ metrics, healStatus }) {
  if (!metrics) return null;

  return (
    <div className="bg-black/30 backdrop-blur-md border border-white/10 p-4 rounded-xl shadow-lg h-full flex flex-col justify-center">
      <h3 className="text-white font-semibold mb-4 tracking-wider text-sm">
        <span className="text-purple-400 mr-2">📊</span> SYSTEM HEALTH
      </h3>
      
      <div className="grid grid-cols-2 gap-4">
        {/* Latency */}
        <div className="bg-white/5 rounded-lg p-3 text-center border border-white/5">
          <div className="text-xs text-gray-400 uppercase tracking-wider mb-1">Latency</div>
          <div className={`text-xl font-mono ${metrics.total_latency > 1500 ? 'text-red-400' : 'text-white'}`}>
            {metrics.total_latency} <span className="text-sm text-gray-500">ms</span>
          </div>
        </div>

        {/* Confidence */}
        <div className="bg-white/5 rounded-lg p-3 text-center border border-white/5">
          <div className="text-xs text-gray-400 uppercase tracking-wider mb-1">Confidence</div>
          <div className={`text-xl font-mono ${metrics.retrieval_confidence < 0.5 ? 'text-yellow-400' : 'text-green-400'}`}>
            {(metrics.retrieval_confidence * 100).toFixed(0)}<span className="text-sm text-gray-500">%</span>
          </div>
        </div>

        {/* Risk */}
        <div className="bg-white/5 rounded-lg p-3 text-center border border-white/5 col-span-2">
          <div className="text-xs text-gray-400 uppercase tracking-wider mb-1">Hallucination Risk</div>
          <div className="w-full bg-gray-800 rounded-full h-2.5 mt-2 overflow-hidden">
            <div 
              className={`h-2.5 rounded-full ${metrics.hallucination_risk > 0.5 ? 'bg-red-500' : 'bg-green-500'}`} 
              style={{ width: `${Math.max(metrics.hallucination_risk * 100, 5)}%` }}
            ></div>
          </div>
        </div>
      </div>
      
      {healStatus && healStatus.anomalies && healStatus.anomalies.length > 0 && (
         <div className="mt-4 p-2 bg-red-900/30 border border-red-500/50 rounded-lg text-xs text-red-200">
           <span className="font-bold">⚠️ Self-Healing Triggered:</span> {healStatus.anomalies.join(", ")}
           <br/><span className="text-red-300/80">Actions: {healStatus.actions_taken.join(", ")}</span>
         </div>
      )}
    </div>
  );
}
