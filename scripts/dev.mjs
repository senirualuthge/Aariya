/**
 * Server launcher (dev or prod) — runs the brain (uvicorn) and UI (vite)
 * servers as children of a single Node process so they die together with the
 * terminal.
 *
 * Cross-platform: macOS, Linux, and Windows (cmd / PowerShell / Windows Terminal).
 *
 * Usage:
 *   npm run dev              Start both servers.
 *   npm run dev -- --clean   Kill leftover uvicorn/vite processes first.
 *   npm run dev -- --prod    Build the UI and serve it (production mode):
 *                            uvicorn without --reload + `vite build` + `vite preview`.
 *
 * Behaviour:
 *  - Ctrl+C (SIGINT), SIGTERM, terminal close (SIGHUP / stdin EOF) — and on
 *    Windows, closing the console window (CTRL_CLOSE_EVENT → SIGHUP) —
 *    stops BOTH servers and prints a shutdown message. The terminal can then
 *    be closed with nothing of ours left running: each server gets its own
 *    process group, so shutdown signals the WHOLE tree (uvicorn's --reload
 *    worker, vite's esbuild child) rather than just the direct child, escalates
 *    to SIGKILL for anything that ignores SIGTERM, and finally verifies that
 *    :8000 and :5173 are free before exiting.
 *  - If one server crashes, the other is stopped too, with a message.
 *  - Never leaves orphaned vite/uvicorn processes behind — including on the
 *    direct process.exit() paths, which are covered by an 'exit' net.
 *  - While booting, prints which server is still starting
 *    (e.g. "Waiting for 🧠 Brain on :8000…"), then a green
 *    "✅ Both servers are ready!" once ports 8000 and 5173 answer.
 *  - With --clean, kills leftover uvicorn/vite processes before starting.
 *  - With --prod, runs `vite build` first, then serves the built UI from `vite
 *    preview` (same ports) and the brain without --reload. If the build fails
 *    or times out (BUILD_TIMEOUT_MS, default 5 min), no servers are started.
 *    On success it prints the dist/ path, bundle size breakdown, and build time,
 *    and warns about any JS chunk over BUILD_CHUNK_WARN_KB (default 500 KB).
 *
 *  Brain ownership:
 *  - In dev the brain (uvicorn) is a child of THIS script, so it always dies
 *    with the terminal — no orphaned process pegging the CPU.
 *  - The persistent launchd agent (com.aariya.backend, managed by
 *    scripts/backend.sh start) is booted out on startup so it can't hold
 *    :8000 or respawn after exit. Persistent mode stays available via
 *    `bash scripts/backend.sh start`.
 */

import { spawn, spawnSync } from 'node:child_process';
import { existsSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import net from 'node:net';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const IS_WIN = process.platform === 'win32';

// ── CLI flags ──────────────────────────────────────────────────────────────
const ARGS = process.argv.slice(2);
const CLEAN = ARGS.includes('--clean') || ARGS.includes('-c');
const PROD = ARGS.includes('--prod');

// ── Colors ──────────────────────────────────────────────────────────────────
// Legacy Windows cmd.exe doesn't render ANSI escapes; Windows Terminal,
// VS Code terminal, and POSIX terminals do. Only emit colors where supported.
const USE_COLORS = !!process.stdout.isTTY && (
  !IS_WIN || !!process.env.WT_SESSION || !!process.env.TERM_PROGRAM || !!process.env.FORCE_COLOR
);
const c = (code) => (USE_COLORS ? `\x1b[${code}m` : '');
const CYAN = c('36');
const MAGENTA = c('35');
const GREEN = c('32');
const YELLOW = c('33');
const RESET = c('0');

// ── Executable resolution (cross-platform) ──────────────────────────────────
function resolveVenvExecutable(name) {
  // Only look in the layout that matches this platform — a venv copied between
  // OSes can contain both Scripts\ and bin\, and picking the foreign one (e.g.
  // a Windows .exe on macOS) fails with EACCES.
  const rel = IS_WIN
    ? path.join('venv', 'Scripts', `${name}.exe`)
    : path.join('venv', 'bin', name);
  const candidate = path.join(ROOT, rel);
  return existsSync(candidate) ? candidate : null;
}

function resolveUvicorn() {
  // Prefer the venv binary; fall back to `python -m uvicorn`, then PATH.
  const bin = resolveVenvExecutable('uvicorn');
  if (bin) return { cmd: bin, args: [] };
  const py = resolveVenvExecutable('python');
  if (py) return { cmd: py, args: ['-m', 'uvicorn'] };
  return { cmd: 'uvicorn', args: [] };
}

function resolveVite() {
  // node_modules/vite/bin/vite.js via the current Node works on every platform
  // (no .cmd wrapper needed); fall back to PATH `vite`.
  const viteJs = path.join(ROOT, 'node_modules', 'vite', 'bin', 'vite.js');
  if (existsSync(viteJs)) return { cmd: process.execPath, args: [viteJs] };
  return { cmd: 'vite', args: [] };
}

const uvicorn = resolveUvicorn();
const vite = resolveVite();

// ── Server definitions ──────────────────────────────────────────────────────
// Prod drops uvicorn --reload (no auto-restart) and serves the pre-built UI
// via `vite preview` instead of the dev server.
const BRAIN = {
  name: '🧠 Brain (uvicorn :8000)',
  short: '🧠 Brain',
  port: 8000,
  cmd: uvicorn.cmd,
  args: [...uvicorn.args, 'server.main:app', '--host', '0.0.0.0', '--port', '8000', ...(PROD ? [] : ['--reload'])],
  color: CYAN,
};

const UI = {
  name: PROD ? '⚡ UI (vite preview :5173)' : '⚡ UI (vite :5173)',
  short: '⚡ UI',
  port: 5173,
  cmd: vite.cmd,
  args: [...vite.args, ...(PROD ? ['preview'] : []), '--host', '0.0.0.0', '--port', '5173', '--strictPort'],
  color: MAGENTA,
};


const servers = [BRAIN, UI];
const children = [];

// Readiness: how long we wait for each server to answer on its port.
const READY_TIMEOUT_MS = 60000;
const READY_POLL_MS = 500;
const READY_HEARTBEAT_MS = 8000;
// Build: how long `vite build` may run before we abort. A hung build must not
// block startup forever. This project builds in ~30s, so 5 min is generous;
// BUILD_TIMEOUT_MS can be overridden via the environment (also handy for tests).
const BUILD_TIMEOUT_MS = Number(process.env.BUILD_TIMEOUT_MS) || 300000;
// Chunk-size warning: flag any single JS chunk larger than this (KB) after a
// build. Tune via BUILD_CHUNK_WARN_KB — vite's own convention warns at 500 kB.
// Raised to 1200 because vendor chunks (tf ~1.1 MB, three ~490 KB) are now
// deliberately isolated via manualChunks; keep in sync with
// chunkSizeWarningLimit in vite.config.js.
const CHUNK_WARN_KB = Number(process.env.BUILD_CHUNK_WARN_KB) || 1200;
// Shutdown: SIGTERM the whole tree, then how long to wait before SIGKILL, and
// the hard ceiling after which we stop waiting and kill whatever still holds
// the dev ports. shutdown() always terminates this script — no path may leave
// servers running after the terminal is gone.
const SHUTDOWN_GRACE_MS = 2500;
const SHUTDOWN_POLL_MS = 250;
const SHUTDOWN_MAX_MS = 10000;

let shuttingDown = false;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function banner() {
  console.log('\n──────────────────────────────────────────────────────');
  console.log(PROD ? '  AARIYA PROD — building & serving' : '  AARIYA DEV — starting servers');
  console.log('──────────────────────────────────────────────────────');
  console.log(`  ${BRAIN.color}${BRAIN.name}${RESET}`);
  console.log(`  ${UI.color}${UI.name}${RESET}`);
  console.log('──────────────────────────────────────────────────────');
  console.log('  Close this terminal or press Ctrl+C to stop both.\n');
}

// ── Process-tree termination ────────────────────────────────────────────────
// A SIGTERM to the *direct* child is not enough to guarantee "nothing related
// is left running":
//   - uvicorn --reload spawns a worker GRANDchild (the reloader usually
//     forwards the signal, but if the reloader is SIGKILLed the worker
//     survives and keeps :8000 bound);
//   - vite spawns an esbuild child;
//   - a SIGKILLed/terminal-closed parent can leave any of them orphaned.
// So each server is started in its OWN process group (detached, POSIX only —
// on Windows `detached` opens a second console and would break stdio inherit)
// and shutdown signals the negated pid, which reaches every descendant.
// Windows has no process groups here, so taskkill /T does the same job.

function isAlive(child) {
  return !!child && child.exitCode === null && child.signalCode === null;
}

/**
 * Signal a server's whole process tree. Returns true when the signal was sent.
 * Sync-safe (used from the process 'exit' handler as a last-resort net).
 */
function killTree(child, signal) {
  if (!isAlive(child) || !child.pid) return false;
  const pid = child.pid;
  try {
    if (IS_WIN) {
      // /T kills the process tree, /F skips the grace period.
      spawnSync('taskkill', ['/F', '/T', '/PID', String(pid)], { stdio: 'ignore' });
    } else {
      process.kill(-pid, signal); // negative pid → the whole process group
    }
    return true;
  } catch {
    // Group already gone (or never created). Try the single process so a
    // half-detached server still gets a chance to die.
    try { child.kill(signal); } catch { /* already gone */ }
    return false;
  }
}

/** Ports still held after the kill — proof that nothing of ours survived. */
async function heldPorts() {
  const held = [];
  for (const server of servers) {
    const pids = await pidsOnPort(server.port);
    if (pids.length > 0) held.push(`:${server.port} (pid ${pids.join(', ')})`);
  }
  return held;
}

async function shutdown(reason, exitCode = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  console.log(`\n${RESET}🛑 Stopping servers — ${reason}`);
  for (const child of children) killTree(child, 'SIGTERM');

  // Poll instead of a blind sleep: escalate as soon as something ignores
  // SIGTERM, and never hang past SHUTDOWN_MAX_MS.
  const startedAt = Date.now();
  let escalated = false;
  while (true) {
    await sleep(SHUTDOWN_POLL_MS);
    const alive = children.filter(isAlive);
    if (alive.length === 0) break;
    const elapsed = Date.now() - startedAt;
    if (!escalated && elapsed >= SHUTDOWN_GRACE_MS) {
      escalated = true;
      console.log(`🛑 ${alive.length} process(es) did not exit on SIGTERM — force-killing.`);
      for (const child of alive) killTree(child, 'SIGKILL');
    }
    if (elapsed >= SHUTDOWN_MAX_MS) {
      console.error('🛑 Could not confirm the servers exited — killing the port holders.');
      for (const server of servers) killPids(await pidsOnPort(server.port));
      break;
    }
  }

  const held = await heldPorts();
  if (held.length > 0) {
    console.error(`🛑 WARNING: something is still listening → ${held.join(', ')}`);
  } else {
    console.log('🛑 All servers stopped. Nothing is left running — safe to close the terminal.');
  }
  process.exit(exitCode);
}

function onExit(child, server) {
  return (code, signal) => {
    if (shuttingDown) return;
    const why = signal ? `signal ${signal}` : `exit code ${code}`;
    console.log(`${server.color}${server.name}${RESET} stopped (${why}).`);
    // The sibling should not keep running alone — stop everything.
    // A server that dies on its own is always a failure, even with code 0.
    shutdown(`${server.name} terminated`, code && code !== 0 ? code : 1);
  };
}

function startServer(server) {
  const child = spawn(server.cmd, server.args, {
    cwd: server.cwd || ROOT,
    // Only force colors when the terminal can render them (legacy cmd.exe cannot).
    env: USE_COLORS ? { ...process.env, FORCE_COLOR: '1' } : process.env,
    stdio: ['ignore', 'inherit', 'inherit'], // keep output visible in terminal
    // Own process group on POSIX so shutdown can signal the whole tree.
    detached: !IS_WIN,
  });
  children.push(child);
  child.on('exit', onExit(child, server));
  child.on('error', (err) => {
    if (shuttingDown) return;
    console.error(`${server.color}${server.name}${RESET} failed to start: ${err.message}`);
    shutdown(`failed to start ${server.name}`, 1);
  });
}

// ── Production build (--prod) ───────────────────────────────────────────────
// Runs `vite build` once before the servers start. Tracked in `children` so a
// Ctrl+C / terminal close during the build aborts it cleanly.
function runBuild() {
  return new Promise((resolve) => {
    const child = spawn(vite.cmd, [...vite.args, 'build'], {
      cwd: ROOT,
      env: USE_COLORS ? { ...process.env, FORCE_COLOR: '1' } : process.env,
      stdio: ['ignore', 'inherit', 'inherit'],
      detached: !IS_WIN, // same group semantics as startServer()
    });
    children.push(child);
    let timer;
    let settled = false;
    const finish = (ok) => {
      if (settled) return; // first outcome wins (exit/error/timeout race)
      settled = true;
      clearTimeout(timer);
      resolve(ok);
    };
    // A hung build must not block startup forever. Abort through the standard
    // shutdown path (SIGTERM → 2.5s grace → SIGKILL → exit 1), which also
    // guarantees the build child can't orphan.
    timer = setTimeout(() => {
      if (shuttingDown) return; // user already aborted — no spurious timeout message
      console.error(`⏰ Build timed out after ${BUILD_TIMEOUT_MS / 1000}s — aborting.`);
      shutdown('build timed out', 1);
    }, BUILD_TIMEOUT_MS);
    child.on('exit', (code, signal) => {
      if (shuttingDown) { finish(false); return; } // aborted by the user
      finish(code === 0 && !signal);
    });
    child.on('error', (err) => {
      if (shuttingDown) { finish(false); return; }
      console.error(`📦 Build failed to start: ${err.message}`);
      finish(false);
    });
  });
}

// ── Build output summary (--prod) ───────────────────────────────────────────
// Walks dist/ after a successful build and reports the total bundle size,
// a per-type breakdown (JS/CSS/HTML/other), and the largest files.
// Pure Node APIs, so it works on every platform.
const LARGEST_FILES = 5;
const TYPE_LABELS = { js: 'JS', css: 'CSS', html: 'HTML', other: 'Other' };

function truncate(str, max) {
  if (str.length <= max) return str;
  const keep = Math.floor((max - 1) / 2);
  return `${str.slice(0, keep)}…${str.slice(-(max - keep - 1))}`;
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return '? B';
  if (bytes < 1024) return `${bytes} B`; // whole bytes below 1 KB
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  const num = value >= 100 ? Math.round(value) : value.toFixed(1);
  return `${num} ${units[unit]}`;
}

function distInfo() {
  const distDir = path.join(ROOT, 'dist');
  if (!existsSync(distDir)) return null;
  try {
    let total = 0;
    let files = 0;
    const byType = { js: { size: 0, count: 0 }, css: { size: 0, count: 0 }, html: { size: 0, count: 0 }, other: { size: 0, count: 0 } };
    const all = [];
    const walk = (dir) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(p);
        else if (entry.isFile()) {
          const size = statSync(p).size;
          total += size;
          files++;
          all.push({ rel: path.relative(distDir, p), size });
          const ext = path.extname(entry.name).slice(1).toLowerCase();
          const type = TYPE_LABELS[ext] ? ext : 'other';
          byType[type].size += size;
          byType[type].count++;
        }
      }
    };
    walk(distDir);
    all.sort((a, b) => b.size - a.size);
    return {
      dir: distDir,
      total,
      files,
      byType,
      largest: all.slice(0, LARGEST_FILES),
      chunks: all.filter((f) => path.extname(f.rel) === '.js'), // all JS chunks, biggest first
    };
  } catch {
    return null; // unreadable/missing mid-walk — just skip the summary
  }
}

// ── Persistent-agent handover ───────────────────────────────────────────────
// The brain may be running as the launchd agent `com.aariya.backend`
// (scripts/backend.sh start, KeepAlive=true). If left loaded it would hold
// :8000, our child uvicorn would die on "address in use", and — worse — any
// port-based kill would make launchd respawn it. So dev owns the brain: boot
// the agent out on startup and wait for the port to free before spawning.
const AGENT_LABEL = 'com.aariya.backend';

async function waitPortFree(port, timeoutMs = 15000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (!(await portOpen(port))) return true;
    await sleep(200);
  }
  return false;
}

async function stopLaunchdBrain() {
  if (process.platform !== 'darwin' || process.env.AARIYA_NO_LAUNCHD === '1') return true;
  // bootout is async — launchd de-registers + SIGTERMs the agent, which then
  // drains its socket. Poll until :8000 is actually free so we never spawn a
  // child that crashes on "address already in use".
  await run(['launchctl', 'bootout', `gui/${process.getuid()}/${AGENT_LABEL}`]);
  return waitPortFree(BRAIN.port);
}

// ── Leftover-process cleanup (--clean) ──────────────────────────────────────
function run(args) {
  return new Promise((resolve) => {
    const child = spawn(args[0], args.slice(1), { stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    child.stdout.on('data', (d) => (out += d));
    child.stderr.on('data', () => {});
    child.on('close', () => resolve(out.trim()));
    child.on('error', () => resolve(''));
  });
}

async function pidsOnPort(port) {
  // Port-based targeting: kill exactly whatever holds the dev ports. Unlike
  // `pkill -f <pattern>`, this can never match an unrelated process whose
  // command line merely contains a string like "vite --host".
  if (IS_WIN) {
    // netstat -ano → "<proto> <local> <remote> <state> <pid>"
    const out = await run(['netstat', '-ano']);
    const pids = new Set();
    for (const line of out.split('\n')) {
      const fields = line.trim().split(/\s+/);
      const local = fields[1] || '';
      // endsWith (not substring match) so a listener on :80000 is never
      // mistaken for :8000; also handles IPv6 [::]:8000 / [::1]:8000.
      if (local.endsWith(`:${port}`) && line.includes('LISTENING')) {
        const pid = fields[fields.length - 1];
        if (pid && /^\d+$/.test(pid)) pids.add(pid);
      }
    }
    return [...pids];
  }
  // lsof -t -i :<port> -sTCP:LISTEN → one PID per line (uvicorn's reloader
  // and worker both hold the socket, so this catches both).
  const out = await run(['lsof', '-t', '-i', `:${port}`, '-sTCP:LISTEN']);
  return out ? out.split('\n').filter(Boolean) : [];
}

async function killPids(pids) {
  const targets = pids.filter((p) => Number(p) !== process.pid);
  const killed = [];
  for (const pid of targets) {
    if (IS_WIN) {
      // Only count it if taskkill actually succeeded (it fails on dead PIDs).
      const out = await run(['taskkill', '/F', '/PID', pid]);
      if (/SUCCESS/i.test(out)) killed.push(pid);
    } else {
      try { process.kill(Number(pid), 'SIGKILL'); killed.push(pid); } catch { /* already gone */ }
    }
  }
  return killed;
}

async function cleanLeftovers() {
  const killed = [];
  for (const port of [BRAIN.port, UI.port]) {
    killed.push(...await killPids(await pidsOnPort(port)));
  }
  return killed;
}

// ── Readiness detection ─────────────────────────────────────────────────────
function portOpen(port, host = '127.0.0.1') {
  return new Promise((resolve) => {
    const socket = net.connect({ port, host });
    const done = (ok) => { socket.destroy(); resolve(ok); };
    // `setTimeout` callback doubles as the timeout handler — no separate listener needed.
    socket.setTimeout(800, () => done(false));
    socket.once('connect', () => done(true));
    socket.once('error', () => done(false));
  });
}

async function waitForReady() {
  const startedAt = Date.now();
  let lastLine = '';
  let lastBeat = 0;
  while (!shuttingDown) {
    const [brainUp, uiUp] = await Promise.all([
      portOpen(BRAIN.port),
      portOpen(UI.port),
      
    ]);
    if (brainUp && uiUp && !shuttingDown) {
      console.log(`${GREEN}✅ All servers are ready!${RESET}`);
      console.log(`${GREEN}   → UI:      http://localhost:${UI.port}${RESET}`);
      console.log(`${GREEN}   → Brain:   http://localhost:${BRAIN.port}${RESET}`);
            return;
    }
    // Tell the user which server(s) are still booting instead of staying silent.
    const waiting = [];
    if (!brainUp) waiting.push(`${BRAIN.color}${BRAIN.short}${RESET} on :${BRAIN.port}`);
    if (!uiUp) waiting.push(`${UI.color}${UI.short}${RESET} on :${UI.port}`);
        const line = `⏳ Waiting for ${waiting.join(' and ')}…`;
    const now = Date.now();
    if (line !== lastLine) {
      console.log(line);
      lastLine = line;
      lastBeat = now;
    } else if (now - lastBeat > READY_HEARTBEAT_MS) {
      // Heartbeat so the user knows it's still polling, not stuck.
      const elapsed = Math.round((now - startedAt) / 1000);
      console.log(`${line} (${elapsed}s)`);
      lastBeat = now;
    }
    if (now - startedAt > READY_TIMEOUT_MS) {
      console.log(`${YELLOW}⏳ Still waiting for servers (timeout after ${READY_TIMEOUT_MS / 1000}s)…${RESET}`);
      return;
    }
    await sleep(READY_POLL_MS);
  }
}

// ── Main ────────────────────────────────────────────────────────────────────
async function main() {
  banner();

  // Dev owns the brain: boot the persistent launchd agent out so our uvicorn
  // child binds :8000 — otherwise the agent holds the port and stays alive
  // (and pegging the CPU) after this script exits.
  await stopLaunchdBrain();

  if (CLEAN) {
    console.log('🧹 Cleaning leftover dev processes…');
    const killed = await cleanLeftovers();
    console.log(killed.length > 0
      ? `🧹 Killed ${killed.length} leftover process(es): ${killed.join(' ')}`
      : '🧹 No leftover processes found.');
    await sleep(600); // let the OS free the ports before spawning
  }

  if (PROD) {
    console.log('📦 Building UI for production…');
    const buildStartedAt = Date.now();
    const ok = await runBuild();
    if (shuttingDown) return; // user aborted during the build
    if (!ok) {
      console.error('❌ Build failed — no servers started.');
      process.exit(1);
    }
    const buildSeconds = (Date.now() - buildStartedAt) / 1000;
    console.log(`${GREEN}✅ Build complete.${RESET}`);
    const dist = distInfo();
    let overChunks = [];
    if (dist) {
      console.log(`${GREEN}   → Output: ${dist.dir}${RESET}`);
      console.log(`${GREEN}   → Bundle: ${formatBytes(dist.total)} · ${dist.files} files${RESET}`);
      const types = Object.entries(dist.byType)
        .filter(([, t]) => t.count > 0)
        .sort((a, b) => b[1].size - a[1].size);
      for (const [key, t] of types) {
        console.log(`${GREEN}     ${TYPE_LABELS[key].padEnd(6)}${formatBytes(t.size).padStart(9)} · ${t.count} file${t.count === 1 ? '' : 's'}${RESET}`);
      }
      if (dist.largest.length > 0) {
        console.log(`${GREEN}     Largest:${RESET}`);
        for (const f of dist.largest) {
          console.log(`${GREEN}     ${truncate(f.rel, 46).padEnd(46)}${formatBytes(f.size).padStart(9)}${RESET}`);
        }
      }
      overChunks = dist.chunks.filter((f) => f.size > CHUNK_WARN_KB * 1024);
    }
    if (overChunks.length > 0) {
      console.log(`${YELLOW}⚠ ${overChunks.length} JS chunk(s) over the ${CHUNK_WARN_KB} KB warn threshold — consider code-splitting:${RESET}`);
      for (const f of overChunks) {
        console.log(`${YELLOW}     ${truncate(f.rel, 46).padEnd(46)}${formatBytes(f.size).padStart(9)}${RESET}`);
      }
    }
    console.log(`${GREEN}   → Build time: ${buildSeconds.toFixed(1)}s${RESET}`);
    // Persist the summary so the analytics dashboard can surface it too.
    try {
      // Drop the internal `chunks` list — downstream only needs the `warnings` subset.
      const { chunks: _chunks, ...distRest } = dist || {};
      writeFileSync(
        path.join(ROOT, '.build-summary.json'),
        JSON.stringify({
          ...distRest,
          warnings: overChunks,
          chunk_warn_kb: CHUNK_WARN_KB,
          build_time_s: buildSeconds,
          built_at: new Date().toISOString(),
        }, null, 2),
      );
    } catch { /* non-fatal: the dashboard just won't show build info */ }
    console.log('Starting production servers…');
  }

  for (const server of servers) startServer(server);

  // Terminal window closed: stdin reaches EOF → treat as terminal close.
  // (On Windows this is a fallback; console close is delivered as SIGHUP.)
  if (process.stdin.isTTY) {
    process.stdin.on('close', () => shutdown('terminal closed'));
    process.stdin.resume();
  }

  // Report readiness once both ports answer.
  void waitForReady();
}

// Signal forwarding (terminal close / Ctrl+C / kill). Registered before the
// children spawn so a Ctrl+C during --clean cleanly aborts startup.
for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(sig, () => shutdown(sig === 'SIGINT' ? 'Ctrl+C pressed' : `${sig} received`));
}

// Last-resort net for the direct process.exit() paths (a failed --prod build,
// an uncaught throw): SIGKILL every tree we started on the way out, so no
// server can outlive this script. Synchronous — 'exit' allows nothing else.
process.on('exit', () => {
  for (const child of children) killTree(child, 'SIGKILL');
});

main();
