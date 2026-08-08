import fs from 'fs';

// The dev launcher (scripts/dev.mjs) writes .build-summary.json after a --prod
// build. This module reads it so chunk warnings can be surfaced in the GUI.
// It is intentionally dependency-free (no electron import) so it can be unit
// tested with a stubbed fs/log. Mirrors the shape of the backend's
// GET /api/build/summary (an envelope with { found, ...data }).
//
//   readBuildSummary({ filePath, fsImpl = fs, log = console })
//     - missing file          -> { found: false } (+ log 'No build summary file yet')
//     - corrupt/unreadable    -> { found: false } (+ log.error)
//     - valid summary         -> { found: true, ...data } (+ warning-count log)
export function readBuildSummary({ filePath, fsImpl = fs, log = console } = {}) {
    try {
        if (!fsImpl.existsSync(filePath)) {
            log.log('[Build] No build summary file yet');
            return { found: false };
        }
        const data = JSON.parse(fsImpl.readFileSync(filePath, 'utf8'));
        const warnings = Array.isArray(data?.warnings) ? data.warnings : [];
        if (warnings.length > 0) {
            log.log(`[Build] ${warnings.length} JS chunk warning(s) — surfacing in GUI`);
        }
        return { found: true, ...data };
    } catch (err) {
        log.error('[Build] Failed to read build summary:', err.message);
        return { found: false };
    }
}
