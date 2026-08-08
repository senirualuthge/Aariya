// src/core/bootProfiler.ts
export type PerfTier = "LOW" | "MID" | "HIGH";

export interface BootProfile {
  cpuScore: number;
  gpuFrameTime: number;
  memoryGB: number;
  cores: number;
  tier: PerfTier;
}

async function cpuBenchmark(): Promise<number> {
  const t0 = performance.now();
  let n = 0;
  // Run simple Math for 50ms
  while (performance.now() - t0 < 50) {
    Math.sqrt(Math.random());
    n++;
  }
  return n;
}

async function gpuBenchmark(): Promise<number> {
  const canvas = document.createElement("canvas");
  const gl = canvas.getContext("webgl");
  if (!gl) return 999;

  const frames = 60;
  const t0 = performance.now();
  for (let i = 0; i < frames; i++) {
    gl.clear(gl.COLOR_BUFFER_BIT);
  }
  const t1 = performance.now();
  return (t1 - t0) / frames;
}

function classifyTier(cpu: number, gpuMs: number, memory: number): PerfTier {
  // Heuristic thresholds
  if (cpu < 20000 || memory <= 4) return "LOW";
  if (gpuMs > 16) return "MID";
  return "HIGH";
}

export async function runBootProfiler(): Promise<BootProfile> {
  const [cpuScore, gpuFrameTime] = await Promise.all([
    cpuBenchmark(),
    gpuBenchmark(),
  ]);

  const memoryGB = (navigator as any).deviceMemory || 4;
  const cores = navigator.hardwareConcurrency || 4;
  const tier = classifyTier(cpuScore, gpuFrameTime, memoryGB);

  console.log(`[Profiler] Detected Tier: ${tier} (CPU: ${cpuScore}, GPU: ${gpuFrameTime.toFixed(2)}ms, RAM: ${memoryGB}GB)`);
  return { cpuScore, gpuFrameTime, memoryGB, cores, tier };
}
