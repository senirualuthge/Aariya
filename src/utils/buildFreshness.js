/**
 * buildFreshness.js
 * ─────────────────
 * Freshness gate for the build-warnings banner: the banner only shows when the
 * build summary is recent, so dev-mode users never see stale warnings from an
 * old `--prod` build. Kept free of any Node/browser imports so it can be
 * unit-tested in plain Node (node:test) and bundled by Vite without issues.
 *
 * The freshness window is configurable via BUILD_WARN_MAX_AGE_HOURS (default
 * 24h). In the renderer it is read from `import.meta.env`:
 *   • BUILD_WARN_MAX_AGE_HOURS  — exposed via vite.config.js `envPrefix`
 *     ['VITE_', 'BUILD_WARN_'] (shell env or .env file; works in dev + build)
 *   • VITE_BUILD_WARN_MAX_AGE_HOURS — the standard Vite `.env` mechanism
 * Either name wins over the 24h default. In plain Node (unit tests) neither
 * exists, so the default applies.
 */

const HOUR_MS = 60 * 60 * 1000;

export const BUILD_WARN_MAX_AGE_HOURS_DEFAULT = 24;

// Resolve a raw env value to a sane hour count; anything that isn't a positive
// number falls back to the default (e.g. unset, '', '0', '-5', 'abc').
export function resolveMaxAgeHours(raw) {
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : BUILD_WARN_MAX_AGE_HOURS_DEFAULT;
}

function readEnvMaxAgeHours() {
  try {
    // Vite statically replaces these two import.meta.env reads (see
    // vite.config.js `envPrefix`); in plain Node import.meta.env is undefined
    // and this throws, which is caught below so the module still imports.
    return import.meta.env.BUILD_WARN_MAX_AGE_HOURS
      || import.meta.env.VITE_BUILD_WARN_MAX_AGE_HOURS
      || undefined;
  } catch {
    return undefined;
  }
}

export const BUILD_WARN_MAX_AGE_HOURS = resolveMaxAgeHours(readEnvMaxAgeHours());
export const BUILD_WARN_MAX_AGE_MS = BUILD_WARN_MAX_AGE_HOURS * HOUR_MS;

/**
 * True when built_at is present, parseable, and within the freshness window.
 * Missing/invalid timestamps are treated as stale (hide the banner); a slightly
 * future-dated timestamp (clock skew on the build machine) still counts as
 * fresh, since the only producer is dev.mjs's `new Date().toISOString()`.
 *
 * @param {string|number|undefined} builtAt ISO string (or timestamp) from the build summary
 * @param {number} now epoch ms — injectable for tests
 * @param {number} maxAgeMs freshness window (default: BUILD_WARN_MAX_AGE_MS)
 */
export function isBuildSummaryFresh(builtAt, now = Date.now(), maxAgeMs = BUILD_WARN_MAX_AGE_MS) {
  if (builtAt === undefined || builtAt === null || builtAt === '') return false;
  // ISO strings parse via Date.parse; raw epoch-ms numbers are used directly
  // (Date.parse would coerce them to a numeric string, which V8 rejects).
  const built = typeof builtAt === 'number' ? builtAt : Date.parse(builtAt);
  if (!Number.isFinite(built)) return false;
  // Only the upper bound matters: anything older than the window is stale, and
  // a negative age (future-dated) is still recent.
  return now - built <= maxAgeMs;
}
