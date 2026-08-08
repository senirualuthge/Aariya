import React from "react";
import PipelineGraph from "./PipelineGraph";
import TimelineBar from "./TimelineBar";
import ChunkViewer from "./ChunkViewer";
import MetricsPanel from "./MetricsPanel";
import VaultContextPanel from "./VaultContextPanel";

export default function RAGDashboard({ rag }) {
  if (!rag) {
    return (
      <div className="flex h-full w-full items-center justify-center p-8 bg-black/60 rounded-xl backdrop-blur">
        <div className="text-center">
          <div className="text-blue-500 mb-4 animate-pulse">
            <svg className="w-8 h-8 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" />
            </svg>
          </div>
          <h2 className="text-xl font-light text-white mb-2">Awaiting Telemetry</h2>
          <p className="text-sm text-gray-400 max-w-sm">
            The RAG pipeline tracer is active but no traces have been generated yet. Talk to the AI demanding facts or knowledge retrieval to trigger a RAG event.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 h-full flex flex-col space-y-6 overflow-y-auto custom-scrollbar">
      {/* Header section with self-healing badge if active */}
      <div className="flex justify-between items-center">
         <div>
            <h2 className="text-2xl font-light text-white tracking-widest uppercase">Cognitive RAG Pipeline</h2>
            <p className="text-sm text-gray-500 mt-1">Trace ID: <span className="font-mono text-gray-400">{rag.trace_id}</span></p>
         </div>
         {rag.self_heal_status && rag.self_heal_status.status === "healing_engaged" && (
            <div className="px-3 py-1 bg-red-500/20 text-red-400 border border-red-500/50 rounded-full text-xs font-bold animate-pulse">
              AUTONOMOUS REMEDIATION ENGAGED
            </div>
         )}
      </div>

      {/* Top half: Graph & Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 h-64">
        <PipelineGraph steps={rag.steps} />
        <MetricsPanel metrics={rag.metrics} healStatus={rag.self_heal_status} />
      </div>

      {/* Timeline span */}
      <div className="w-full">
        <TimelineBar steps={rag.steps} />
      </div>

      {/* Obsidian vault context — what was pulled from each vault */}
      <div className="w-full">
        <VaultContextPanel raw={rag.obsidian_vault_context} />
      </div>

      {/* Context chunks */}
      <div className="w-full">
        <ChunkViewer chunks={rag.chunks} />
      </div>
    </div>
  );
}
