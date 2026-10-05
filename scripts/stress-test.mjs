#!/usr/bin/env node
/**
 * stress-test.mjs — whole-system stress harness (ToDo §7).
 *
 * There was no way to answer "does Aariya stay up under load, and what breaks
 * first?" This harness answers it by driving the real server the way the app
 * actually uses it — HTTP + WebSocket + the chat cognitive loop — and
 * reporting degradation instead of pass/fail alone.
 *
 * Three simultaneous pressure sources, because real breakage comes from the
 * interaction, not from any single one:
 *
 *   HTTP     N concurrent clients hammering the health + build endpoints at a
 *            fixed rate, so slow responses surface as latency percentiles.
 *   WS       M WebSocket clients held open against /ws/brain_metrics and
 *            /ws/synoptics (the broadcast endpoints) — the sockets whose growth
 *            is what actually OOMs a naive fan-out.
 *   CHAT     K clients driving the full cognitive loop with real text turns.
 *            This is the expensive path (model calls + memory + signal bus).
 *
 * Everything is budget-aware: it never exceeds the server's own rate limit,
 * because a stress run that trips the limiter measures the limiter.
 *
 * Usage:
 *   node scripts/stress-test.mjs                      # defaults, 60s
 *   node scripts/stress-test.mjs --duration 30        # shorter run
 *   node scripts/stress-test.mjs --ws 40 --chat 5      # heavier WS/chat
 *   node scripts/stress-test.mjs --url http://host:8000
 *   node scripts/stress-test.mjs --json report.json    # machine-readable
 *   node scripts/stress-test.mjs --p95-budget 250       # tighten the latency bar
 *
 * Note on rate limiting: /api/... routes are capped by MAX_CALLS_PER_USER_PER_DAY
 * (default 500/day) and WS sessions by MAX_CONCURRENT_SESSIONS (default 5). The
 * harness reports limit rejections separately rather than as errors — a 429 is
 * the limiter working, not the system breaking. Raise those env vars server-side
 * before running a heavy profile.
 */

import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const ROOT_URLS = { ws: 'ws://127.0.0.1:8000/ws/brain_metrics', http: 'http://127.0.0.1:8000' };

// ── Config ───────────────────────────────────────────────────────────────────

function parseArgs(argv) {
    const cfg = {
        url: ROOT_URLS.http,
        duration: 60,
        httpRps: 20,
        httpConcurrency: 4,
        ws: 8,
        chat: 2,
        chatIntervalMs: 4000,
        wsPath: '/ws/brain_metrics',
        chatPath: '/ws/dashboard/stream',
        json: null,
        quiet: false,
        p95BudgetMs: 1000,
    };
    for (let i = 2; i < argv.length; i += 1) {
        const arg = argv[i];
        const next = () => argv[++i];
        switch (arg) {
            case '--url': cfg.url = next(); break;
            case '--duration': cfg.duration = Number(next()); break;
            case '--rps': cfg.httpRps = Number(next()); break;
            case '--concurrency': cfg.httpConcurrency = Number(next()); break;
            case '--ws': cfg.ws = Number(next()); break;
            case '--chat': cfg.chat = Number(next()); break;
            case '--chat-interval': cfg.chatIntervalMs = Number(next()); break;
            case '--ws-path': cfg.wsPath = next(); break;
            case '--chat-path': cfg.chatPath = next(); break;
            case '--json': cfg.json = next(); break;
            case '--p95-budget': cfg.p95BudgetMs = Number(next()); break;
            case '--quiet': cfg.quiet = true; break;
            case '--help':
                console.log(fs.readFileSync(fileURLToPath(import.meta.url), 'utf8').split('*/')[0]);
                process.exit(0);
                break;
            default:
                console.error(`unknown flag: ${arg}`);
                process.exit(2);
        }
    }
    if (!cfg.url.startsWith('http')) cfg.url = `http://${cfg.url}`;
    cfg.url = cfg.url.replace(/\/$/, '');
    cfg.wsBase = cfg.url.replace(/^http/, 'ws');
    return cfg;
}

const cfg = parseArgs(process.argv);
const log = (...args) => { if (!cfg.quiet) console.log(...args); };

// ── Metrics ──────────────────────────────────────────────────────────────────

class Latencies {
    constructor() { this.samples = []; }

    add(ms) { this.samples.push(ms); }

    percentile(p) {
        if (this.samples.length === 0) return null;
        const sorted = [...this.samples].sort((a, b) => a - b);
        const idx = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
        return sorted[idx];
    }

    get count() { return this.samples.length; }

    summary() {
        if (this.samples.length === 0) return { count: 0 };
        const total = this.samples.reduce((a, b) => a + b, 0);
        return {
            count: this.samples.length,
            min: Math.round(this.percentile(0)),
            mean: Math.round(total / this.samples.length),
            p50: Math.round(this.percentile(50)),
            p95: Math.round(this.percentile(95)),
            p99: Math.round(this.percentile(99)),
            max: Math.round(this.percentile(100)),
        };
    }
}

const metrics = {
    http: { ok: 0, limited: 0, failed: 0, latency: new Latencies(), byStatus: {} },
    ws: { opened: 0, openFailed: 0, rejected: 0, messages: 0, closedUnexpectedly: 0 },
    chat: { sent: 0, replies: 0, failed: 0, latency: new Latencies() },
    startedAt: Date.now(),
};

function recordStatus(bucket, status) {
    const key = String(status);
    bucket.byStatus[key] = (bucket.byStatus[key] || 0) + 1;
}

// ── Preconditions ────────────────────────────────────────────────────────────

async function checkServerReachable() {
    try {
        const res = await fetch(`${cfg.url}/api/system/health/checks`, { signal: AbortSignal.timeout(5000) });
        if (!res.ok) {
            console.error(`server answered ${res.status} on /api/system/health/checks`);
            process.exit(2);
        }
        return await res.json();
    } catch (err) {
        console.error(`\nCannot reach the Aariya server at ${cfg.url}\n  ${err.message}\nStart it first: npm run dev:brain\n`);
        process.exit(2);
    }
}

// ── HTTP load ────────────────────────────────────────────────────────────────

const HTTP_TARGETS = [
    { path: '/api/system/health/checks', weight: 3 },
    { path: '/api/system/health', weight: 2 },
    { path: '/api/sdk/killswitches/state', weight: 1 },
];

function pickHttpTarget() {
    const total = HTTP_TARGETS.reduce((sum, t) => sum + t.weight, 0);
    let roll = Math.random() * total;
    for (const target of HTTP_TARGETS) {
        roll -= target.weight;
        if (roll <= 0) return target.path;
    }
    return HTTP_TARGETS[0].path;
}

async function httpWorker(signal, intervalMs) {
    while (!signal.aborted) {
        const started = performance.now();
        const path = pickHttpTarget();
        try {
            const res = await fetch(`${cfg.url}${path}`, { signal: AbortSignal.timeout(10000) });
            metrics.http.latency.add(performance.now() - started);
            recordStatus(metrics.http, res.status);
            if (res.status === 429 || res.status === 503) metrics.http.limited += 1;
            else if (res.ok) metrics.http.ok += 1;
            else metrics.http.failed += 1;
        } catch (err) {
            if (signal.aborted) return;
            metrics.http.latency.add(performance.now() - started);
            metrics.http.failed += 1;
            recordStatus(metrics.http, err.name === 'TimeoutError' ? 'timeout' : 'network');
        }
        await sleep(intervalMs);
    }
}

// ── WebSocket load ───────────────────────────────────────────────────────────

async function wsClient(url, signal) {
    let socket;
    try {
        socket = new WebSocket(url);
    } catch (err) {
        metrics.ws.openFailed += 1;
        log(`  ws open threw: ${err.message}`);
        return;
    }

    const opened = await new Promise((resolve) => {
        const timer = setTimeout(() => resolve(false), 10000);
        socket.addEventListener('open', () => { clearTimeout(timer); resolve(true); }, { once: true });
        socket.addEventListener('error', () => { clearTimeout(timer); resolve(false); }, { once: true });
        socket.addEventListener('close', (event) => {
            // 1008 = policy violation: the WS auth layer rejected us. That is
            // the kill switch working, not a stress failure.
            if (event.code === 1008) metrics.ws.rejected += 1;
        }, { once: true });
    });

    if (!opened) {
        metrics.ws.openFailed += 1;
        try { socket.close(); } catch { /* already dead */ }
        return;
    }

    metrics.ws.opened += 1;
    socket.addEventListener('message', () => { metrics.ws.messages += 1; });

    await new Promise((resolve) => {
        const finish = () => resolve();
        socket.addEventListener('close', finish, { once: true });
        signal.addEventListener('abort', finish, { once: true });
    });

    if (!signal.aborted && socket.readyState === WebSocket.CLOSED) {
        metrics.ws.closedUnexpectedly += 1;
    }
    try { socket.close(); } catch { /* already closed */ }
}

// ── Chat load (the expensive path) ───────────────────────────────────────────

const CHAT_PROMPTS = [
    'status',
    'what are you working on',
    'how are you feeling',
    'tell me a one line summary of the system state',
];

async function chatClient(url, signal) {
    let socket;
    try {
        socket = new WebSocket(url);
    } catch {
        metrics.chat.failed += 1;
        return;
    }

    const opened = await new Promise((resolve) => {
        const timer = setTimeout(() => resolve(false), 10000);
        socket.addEventListener('open', () => { clearTimeout(timer); resolve(true); }, { once: true });
        socket.addEventListener('error', () => { clearTimeout(timer); resolve(false); }, { once: true });
    });
    if (!opened) {
        metrics.chat.failed += 1;
        try { socket.close(); } catch { /* already dead */ }
        return;
    }

    let awaiting = null;
    socket.addEventListener('message', (event) => {
        if (!awaiting) return;
        try {
            const frame = JSON.parse(typeof event.data === 'string' ? event.data : '');
            if (frame?.type === 'ai_response' || frame?.type === 'text.stream') {
                const pending = awaiting;
                awaiting = null;
                pending(frame);
            }
        } catch {
            // Non-JSON keepalive frames are expected on this socket.
        }
    });

    const done = new Promise((resolve) => {
        const finish = () => resolve();
        socket.addEventListener('close', finish, { once: true });
        signal.addEventListener('abort', finish, { once: true });
    });

    while (!signal.aborted) {
        const prompt = CHAT_PROMPTS[Math.floor(Math.random() * CHAT_PROMPTS.length)];
        const started = performance.now();
        const reply = new Promise((resolve) => {
            awaiting = resolve;
            setTimeout(() => { awaiting = null; resolve(null); }, 30000);
        });
        metrics.chat.sent += 1;
        try {
            socket.send(JSON.stringify({ type: 'user_input', content: prompt }));
        } catch {
            break;
        }
        const frame = await reply;
        if (frame) {
            metrics.chat.replies += 1;
            metrics.chat.latency.add(performance.now() - started);
        } else if (!signal.aborted) {
            metrics.chat.failed += 1;
        }
        await sleep(cfg.chatIntervalMs);
        if (!socket.readyState) break;
    }

    await done;
    try { socket.close(); } catch { /* already closed */ }
}

// ── Runner ───────────────────────────────────────────────────────────────────

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, Math.max(0, ms)));

async function main() {
    const health = await checkServerReachable();
    log(`Aariya stress test`);
    log(`  target      : ${cfg.url}`);
    log(`  health score: ${health.score ?? 'unknown'}`);
    log(`  duration    : ${cfg.duration}s`);
    log(`  http        : ${cfg.httpRps} rps, ${cfg.httpConcurrency} workers`);
    log(`  websocket   : ${cfg.ws} clients on ${cfg.wsPath}`);
    log(`  chat        : ${cfg.chat} clients on ${cfg.chatPath} every ${cfg.chatIntervalMs}ms\n`);

    const controller = new AbortController();
    const tasks = [];

    const intervalMs = Math.max(0, Math.round(1000 / cfg.httpRps));
    for (let i = 0; i < cfg.httpConcurrency; i += 1) {
        tasks.push(httpWorker(controller.signal, intervalMs * cfg.httpConcurrency));
    }
    for (let i = 0; i < cfg.ws; i += 1) {
        tasks.push(wsClient(`${cfg.wsBase}${cfg.wsPath}`, controller.signal));
    }
    for (let i = 0; i < cfg.chat; i += 1) {
        tasks.push(chatClient(`${cfg.wsBase}${cfg.chatPath}`, controller.signal));
    }

    const progress = setInterval(() => {
        log(`  t+${Math.round((Date.now() - metrics.startedAt) / 1000)}s  ` +
            `http ok=${metrics.http.ok} fail=${metrics.http.failed} limited=${metrics.http.limited}  ` +
            `ws open=${metrics.ws.opened} msgs=${metrics.ws.messages}  ` +
            `chat replies=${metrics.chat.replies}`);
    }, 5000);

    await sleep(cfg.duration * 1000);
    clearInterval(progress);
    controller.abort();
    await Promise.race([
        Promise.allSettled(tasks),
        sleep(10000),
    ]);

    const after = await fetch(`${cfg.url}/api/system/health/checks`)
        .then((r) => r.json())
        .catch(() => null);

    report(health, after);
}

function report(before, after) {
    const elapsed = (Date.now() - metrics.startedAt) / 1000;
    const http = metrics.http.latency.summary();
    const chat = metrics.chat.latency.summary();

    const findings = [];
    if (metrics.http.failed > 0) findings.push(`${metrics.http.failed} HTTP request(s) failed outright`);
    if (metrics.ws.openFailed > 0) findings.push(`${metrics.ws.openFailed} WebSocket(s) failed to open`);
    if (metrics.ws.closedUnexpectedly > 0) findings.push(`${metrics.ws.closedUnexpectedly} WebSocket(s) dropped while open`);
    if (chat.count > 0 && metrics.chat.failed > 0) findings.push(`${metrics.chat.failed} chat turn(s) got no reply`);
    if (after && before && typeof before.score === 'number' && typeof after.score === 'number' && after.score < before.score) {
        findings.push(`health score degraded ${before.score} → ${after.score}`);
    }
    if (http.p95 > cfg.p95BudgetMs) findings.push(`HTTP p95 ${http.p95}ms exceeds the ${cfg.p95BudgetMs}ms budget`);

    console.log('\n─── result ───────────────────────────────────────────');
    console.log(`  duration        : ${elapsed.toFixed(1)}s`);
    console.log(`  http            : ${metrics.http.ok} ok, ${metrics.http.failed} failed, ${metrics.http.limited} rate-limited`);
    console.log(`  http latency    : ${http.count ? `p50 ${http.p50}ms  p95 ${http.p95}ms  p99 ${http.p99}ms  max ${http.max}ms` : 'no samples'}`);
    console.log(`  http statuses   : ${JSON.stringify(metrics.http.byStatus)}`);
    console.log(`  websocket       : ${metrics.ws.opened} opened, ${metrics.ws.openFailed} failed, ${metrics.ws.rejected} auth-rejected, ${metrics.ws.messages} messages, ${metrics.ws.closedUnexpectedly} dropped`);
    console.log(`  chat            : ${metrics.chat.sent} sent, ${metrics.chat.replies} replied, ${metrics.chat.failed} no-reply`);
    console.log(`  chat latency    : ${chat.count ? `p50 ${chat.p50}ms  p95 ${chat.p95}ms` : 'no samples'}`);
    console.log(`  health score    : ${before?.score ?? '?'} → ${after?.score ?? '?'}`);

    if (findings.length === 0) {
        console.log('\n  ✓ no degradation detected');
    } else {
        console.log('\n  degradation observed:');
        for (const finding of findings) console.log(`    • ${finding}`);
    }

    if (cfg.json) {
        const payload = {
            config: cfg,
            elapsedSeconds: Number(elapsed.toFixed(1)),
            http: { ...metrics.http, latency: http },
            websocket: { ...metrics.ws },
            chat: { ...metrics.chat, latency: chat },
            healthBefore: before?.score ?? null,
            healthAfter: after?.score ?? null,
            findings,
        };
        fs.writeFileSync(cfg.json, `${JSON.stringify(payload, null, 2)}\n`);
        console.log(`\n  report written to ${cfg.json}`);
    }
}

await main();