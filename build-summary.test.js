import test from 'node:test';
import assert from 'node:assert/strict';
import { readBuildSummary } from './build-summary.js';
import {
  isBuildSummaryFresh,
  resolveMaxAgeHours,
  BUILD_WARN_MAX_AGE_HOURS,
  BUILD_WARN_MAX_AGE_MS,
} from './src/utils/buildFreshness.js';

// ── Stubs ──────────────────────────────────────────────────────────────────
// A minimal fs-like object; every method throws unless overridden, so a test
// only exercises the code path it intends to.
function makeFs(overrides = {}) {
    return {
        existsSync: overrides.existsSync ?? (() => false),
        readFileSync: overrides.readFileSync ?? (() => {
            throw new Error('readFileSync not stubbed');
        }),
    };
}

// Captures console-style calls: { log: [...], error: [...] }.
function makeLog() {
    const calls = { log: [], error: [] };
    return {
        calls,
        log: (...args) => calls.log.push(args),
        error: (...args) => calls.error.push(args),
    };
}

const FILE = '/fake/path/.build-summary.json';

// ── Cases ──────────────────────────────────────────────────────────────────
test('returns {found:false} when the summary file is missing', () => {
    const fsStub = makeFs({ existsSync: () => false });
    const log = makeLog();

    const result = readBuildSummary({ filePath: FILE, fsImpl: fsStub, log });

    assert.deepEqual(result, { found: false });
    assert.equal(log.calls.log.length, 1);
    assert.match(log.calls.log[0][0], /No build summary file yet/);
    assert.equal(log.calls.error.length, 0);
});

test('returns {found:false} and logs an error when the JSON is corrupt', () => {
    const fsStub = makeFs({
        existsSync: () => true,
        readFileSync: () => '{ not valid json !!',
    });
    const log = makeLog();

    const result = readBuildSummary({ filePath: FILE, fsImpl: fsStub, log });

    assert.deepEqual(result, { found: false });
    assert.equal(log.calls.error.length, 1);
    assert.match(log.calls.error[0][0], /Failed to read build summary/);
    assert.equal(typeof log.calls.error[0][1], 'string', 'error message should be included');
});

test('returns the full summary and logs a count when chunk warnings are present', () => {
    const summary = {
        total_size: 3000000,
        file_count: 12,
        build_time_s: 4.1,
        chunk_warn_kb: 500,
        built_at: '2026-08-05T10:00:00.000Z',
        warnings: [
            { rel: 'assets/index-abc123.js', size: 2100000 },
            { rel: 'assets/vendor-xyz.js', size: 620000 },
        ],
    };
    const fsStub = makeFs({
        existsSync: () => true,
        readFileSync: () => JSON.stringify(summary),
    });
    const log = makeLog();

    const result = readBuildSummary({ filePath: FILE, fsImpl: fsStub, log });

    assert.equal(result.found, true);
    assert.equal(result.total_size, 3000000);
    assert.equal(result.warnings.length, 2);
    assert.deepEqual(result.warnings[0], { rel: 'assets/index-abc123.js', size: 2100000 });
    assert.equal(result.chunk_warn_kb, 500);
    assert.equal(log.calls.log.length, 1);
    assert.match(log.calls.log[0][0], /2 JS chunk warning\(s\) — surfacing in GUI/);
});

test('returns the summary untouched and logs nothing when warnings is not an array', () => {
    const fsStub = makeFs({
        existsSync: () => true,
        readFileSync: () => JSON.stringify({ total_size: 99, warnings: 'oops' }),
    });
    const log = makeLog();

    const result = readBuildSummary({ filePath: FILE, fsImpl: fsStub, log });

    // The Array.isArray guard only affects the log; the spread keeps the file data.
    assert.deepEqual(result, { found: true, total_size: 99, warnings: 'oops' });
    assert.equal(log.calls.log.length, 0);
    assert.equal(log.calls.error.length, 0);
});

test('returns {found:true} and does not log when a valid summary has no warnings', () => {
    const fsStub = makeFs({
        existsSync: () => true,
        readFileSync: () => JSON.stringify({ total_size: 42 }),
    });
    const log = makeLog();

    const result = readBuildSummary({ filePath: FILE, fsImpl: fsStub, log });

    assert.deepEqual(result, { found: true, total_size: 42 });
    assert.equal(log.calls.log.length, 0);
    assert.equal(log.calls.error.length, 0);
});

// ── Freshness gate (build-warnings banner) ────────────────────────────────
const HOUR = 60 * 60 * 1000;
const NOW = Date.parse('2026-08-05T12:00:00.000Z');

test('isBuildSummaryFresh: a recent summary is fresh', () => {
    assert.equal(isBuildSummaryFresh('2026-08-05T10:00:00.000Z', NOW), true);
});

test('isBuildSummaryFresh: exactly at the 24h boundary is still fresh', () => {
    assert.equal(isBuildSummaryFresh('2026-08-04T12:00:00.000Z', NOW), true);
});

test('isBuildSummaryFresh: older than 24h is stale', () => {
    assert.equal(isBuildSummaryFresh('2026-08-04T11:00:00.000Z', NOW), false);
    assert.equal(isBuildSummaryFresh('2026-08-01T12:00:00.000Z', NOW), false);
});

test('isBuildSummaryFresh: missing built_at is stale', () => {
    assert.equal(isBuildSummaryFresh(undefined, NOW), false);
    assert.equal(isBuildSummaryFresh(null, NOW), false);
    assert.equal(isBuildSummaryFresh('', NOW), false);
});

test('isBuildSummaryFresh: unparseable built_at is stale', () => {
    assert.equal(isBuildSummaryFresh('not-a-date', NOW), false);
    assert.equal(isBuildSummaryFresh('2026-99-99', NOW), false);
});

test('isBuildSummaryFresh: slightly future-dated built_at is fresh (clock skew)', () => {
    assert.equal(isBuildSummaryFresh('2026-08-05T12:30:00.000Z', NOW), true);
});

test('isBuildSummaryFresh: honors a custom maxAgeMs window', () => {
    assert.equal(isBuildSummaryFresh('2026-08-05T06:00:00.000Z', NOW, 5 * HOUR), false);
    assert.equal(isBuildSummaryFresh('2026-08-05T08:00:00.000Z', NOW, 5 * HOUR), true);
});

test('isBuildSummaryFresh: accepts raw numeric epoch-ms timestamps too', () => {
    const builtMs = NOW - 2 * HOUR;
    assert.equal(isBuildSummaryFresh(builtMs, NOW), true);
    assert.equal(isBuildSummaryFresh(NOW - 30 * HOUR, NOW), false);
});

// ── Configurable freshness window (BUILD_WARN_MAX_AGE_HOURS) ────────────────
test('resolveMaxAgeHours: defaults to 24 for unset/invalid values', () => {
    assert.equal(resolveMaxAgeHours(undefined), 24);
    assert.equal(resolveMaxAgeHours(''), 24);
    assert.equal(resolveMaxAgeHours('0'), 24);
    assert.equal(resolveMaxAgeHours('-5'), 24);
    assert.equal(resolveMaxAgeHours('abc'), 24);
});

test('resolveMaxAgeHours: uses positive numeric values', () => {
    assert.equal(resolveMaxAgeHours('48'), 48);
    assert.equal(resolveMaxAgeHours(72), 72);
    assert.equal(resolveMaxAgeHours('2.5'), 2.5);
});

test('module freshness window defaults to 24h in a plain-Node environment', () => {
    // Plain Node has no import.meta.env, so the module must fall back to 24h.
    assert.equal(BUILD_WARN_MAX_AGE_HOURS, 24);
    assert.equal(BUILD_WARN_MAX_AGE_MS, 24 * HOUR);
});

test('isBuildSummaryFresh: honors the configured window when passed as maxAgeMs', () => {
    // 30h-old summary: stale with the default 24h, fresh with a 48h window.
    const built30h = '2026-08-04T06:00:00.000Z';
    assert.equal(isBuildSummaryFresh(built30h, NOW), false);
    assert.equal(isBuildSummaryFresh(built30h, NOW, 48 * HOUR), true);
});
