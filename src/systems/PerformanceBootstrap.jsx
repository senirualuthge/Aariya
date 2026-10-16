import { useEffect } from 'react';
import useStore from '../store';
import { runBootProfiler } from '../core/bootProfiler';
import { createRuntimeConfig } from '../core/runtimeConfig';
import { tripleLoopRuntime } from '../core/tripleLoopRuntime';
import { thermalController } from '../core/thermalController';
import { fpsController } from '../core/fpsController';

/**
 * PerformanceBootstrap — starts the Phase-1 performance runtime.
 *
 * Boot profiler → runtime config → triple-loop runtime → FPS/thermal governors,
 * all measured from the REAL render loop (no synthetic input).
 *
 * Deliberately does NOT go through `initializePerformanceSystem`: that path also
 * wires the msgpack telemetry WebSocket and the face worker. The app already owns
 * its own JSON WebSocket (`brainClient`) and camera pipeline, so activating that
 * path would open a second connection and double-run face detection — and it
 * pulls in an undeclared `@msgpack/msgpack` dependency. We activate only the
 * measurement/enforcement pieces.
 *
 * Idempotent (concurrent StrictMode mounts share one boot promise) and
 * degrades gracefully: a failure leaves the UI running and just logs.
 */
let bootPromise = null;

function bootstrapPerformance() {
    if (bootPromise) return bootPromise;

    bootPromise = (async () => {
        const profile = await runBootProfiler();
        const config = createRuntimeConfig(profile.tier);

        tripleLoopRuntime.setConfig(config);
        thermalController.setConfig(config);

        // Govern FPS + thermal from real render-loop frame timing.
        tripleLoopRuntime.subscribeRender((deltaTime) => {
            const frameTimeMs = deltaTime * 1000;
            fpsController.update(deltaTime, frameTimeMs);
            thermalController.update(deltaTime, frameTimeMs, frameTimeMs);
        }, -100, 'FPS & Thermal Controller');

        // Start the loops before applying the FPS cap: on a ≥120 Hz display
        // `fpsController.start()` can run a ~4 s perf test, and the loops must
        // not wait on that. It respects the saved mode (localStorage 'fpsMode').
        tripleLoopRuntime.startAll();
        fpsController.start().catch((err) => {
            console.warn('[Perf] FPS controller start failed (degraded):', err);
        });

        return { tier: profile.tier, tripleLoop: tripleLoopRuntime.getStatus() };
    })().catch((err) => {
        bootPromise = null; // allow a later retry
        throw err;
    });

    return bootPromise;
}

export default function PerformanceBootstrap() {
    const started = useStore((state) => state.started);

    useEffect(() => {
        if (!started) return undefined;
        let active = true;
        bootstrapPerformance()
            .then((status) => {
                if (active && status) console.log('[Perf] runtime ready:', status.tripleLoop);
            })
            .catch((err) => {
                if (active) console.warn('[Perf] bootstrap failed (degraded):', err);
            });
        return () => { active = false; };
    }, [started]);

    return null;
}
