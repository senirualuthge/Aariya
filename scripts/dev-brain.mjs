/**
 * Foreground uvicorn launcher for the brain — `npm run dev:brain`.
 *
 * Why this exists: the npm script used to hardcode an absolute interpreter path
 * from one developer's machine, so `npm run dev:brain` only worked there. This
 * resolves the interpreter the same way scripts/dev.mjs does (same convention,
 * same venv layout rules), then execs uvicorn in the foreground so the terminal
 * keeps the process attached.
 *
 * Override with AARIYA_PYTHON=/path/to/python.
 */
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const IS_WIN = process.platform === 'win32';

// Only look in the layout that matches this platform — a venv copied between
// OSes can contain both Scripts\ and bin\, and picking the foreign one fails.
function venvPython() {
  const rel = IS_WIN
    ? path.join('venv', 'Scripts', 'python.exe')
    : path.join('venv', 'bin', 'python');
  const candidate = path.join(ROOT, rel);
  return existsSync(candidate) ? candidate : null;
}

export function resolvePython() {
  if (process.env.AARIYA_PYTHON) return process.env.AARIYA_PYTHON;
  return venvPython();
}

const python = resolvePython();
if (!python) {
  console.error(
    'No interpreter found. Create the venv (./setup.sh or ./setup.ps1) '
    + 'or set AARIYA_PYTHON=/path/to/python.',
  );
  process.exit(1);
}

const child = spawn(
  python,
  ['-m', 'uvicorn', 'server.main:app', '--host', '0.0.0.0', '--port', process.env.AARIYA_PORT || '8000', '--reload'],
  { cwd: ROOT, stdio: 'inherit' },
);

child.on('exit', (code, signal) => {
  process.exit(signal ? 1 : code ?? 0);
});
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => child.kill(sig));
}