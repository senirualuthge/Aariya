/* global process */
import { app, BrowserWindow, session, ipcMain } from 'electron';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';
import { spawn } from 'child_process';
import { readBuildSummary } from './build-summary.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// `npm run gui` opens the desktop window and NOTHING else. The brain (:8000) and
// the UI (:5173) are owned exclusively by `npm run dev` (scripts/dev.mjs) — the
// same launch pair `run_gui.sh` used to glue together. Starting a second uvicorn
// from here used to fight the launcher's brain for :8000, and silently serving a
// stale dist/ build over file:// when no UI server was up meant the window could
// show a different app than `npm run dev` — with camera/mic dead, because a
// file:// page is not the secure origin the dev server provides.
const DEV_SERVER_URL = 'http://127.0.0.1:5173';
const DEV_SERVER_ORIGIN = new URL(DEV_SERVER_URL).origin;

// Capture devices the app is allowed to open. Without these grants every
// getUserMedia call is denied before the OS prompt, which is what made the
// camera/mic stay dark in the GUI.
const MEDIA_PERMISSIONS = new Set(['microphone', 'camera', 'media']);

let mainWindow;
let analyticsWindow;

/**
 * Grant mic/camera to the app's own origin only. A blanket grant would hand
 * capture to any page the window is ever pointed at.
 */
function isOurOrigin(requestingUrl) {
    try {
        return new URL(requestingUrl || '').origin === DEV_SERVER_ORIGIN;
    } catch {
        return false;
    }
}

/**
 * Block until the dev server answers on DEV_SERVER_URL.
 * Returns false when it is not up (after a short grace period, so an
 * `npm run dev` that is still booting is not reported as "not running").
 */
async function waitForDevServer(url, retries = 20, delayMs = 500) {
    for (let i = 0; i < retries; i++) {
        try {
            await fetch(url);
            return true;
        } catch {
            // Heartbeat only — a booting `npm run dev` can take a few seconds
            // and one line every 2s is enough to show we're still waiting.
            if (i > 0 && i % 4 === 0) console.log('[Main] Waiting for the UI server…');
            await new Promise(r => setTimeout(r, delayMs));
        }
    }
    return false;
}

async function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1400,
        height: 900,
        title: 'Aariya AI Companion',
        backgroundColor: '#0a0e1a',
        show: false, // Prevents blank/white flash
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.cjs')
        },
        autoHideMenuBar: true
    });

    // Register BEFORE any load call so the event is never missed
    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
    });

    mainWindow.on('closed', () => {
        mainWindow = null;
    });

    // The window ALWAYS loads the dev server — the same origin, bundle and
    // feature behaviour as `npm run dev`. No dist/ fallback: a stale build over
    // file:// is exactly the version mismatch this launcher used to create.
    console.log(`[Main] Loading ${DEV_SERVER_URL}`);
    mainWindow.loadURL(DEV_SERVER_URL);
}

// ── Build summary (chunk warnings) ─────────────────────────────────────────
// The dev launcher (scripts/dev.mjs) writes .build-summary.json after a --prod
// build; the renderer asks for it via IPC so chunk warnings can be surfaced in
// the GUI without the user opening the terminal. Delegates to the testable
// readBuildSummary() helper (injectable fs/log) in build-summary.js.
ipcMain.handle('get-build-summary', () =>
    readBuildSummary({ filePath: path.join(__dirname, '.build-summary.json') })
);

// ── Panel persistence via main-process fs (crash-safe, survives SIGINT) ──
function getPanelStatePath() {
    return path.join(app.getPath('userData'), 'panel-state.json');
}

ipcMain.handle('save-panel-state', (_event, state) => {
    try {
        const filePath = getPanelStatePath();
        fs.writeFileSync(filePath, JSON.stringify(state), 'utf8');
        console.log('[IPC] Saved panel state to:', filePath);
    } catch (err) {
        console.error('[Panel] Failed to save panel state:', err);
    }
});

ipcMain.handle('load-panel-state', () => {
    try {
        const filePath = getPanelStatePath();
        console.log('[IPC] Loading panel state from:', filePath);
        if (fs.existsSync(filePath)) {
            const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
            console.log('[IPC] Loaded panel state with keys:', Object.keys(data));
            return data;
        }
        console.log('[IPC] Panel state file does not exist. Returning empty object.');
    } catch (err) {
        console.error('[Panel] Failed to load panel state:', err);
    }
    return {};
});

// IPC Handler for Habit Tracker
ipcMain.handle('get-habit-stats', async () => {
    return new Promise((resolve) => {
        // Using relative path to habit tracker
        const scriptDir = path.join(__dirname, 'HabitTracker');
        const scriptPath = path.join(scriptDir, 'main.py');
        console.log('Spawning habit tracker stats:', scriptPath);
        
        // IMPORTANT: Set cwd to the script directory so it finds habits.db correctly
        const pythonProcess = spawn('python', ['main.py', 'stats'], { cwd: scriptDir });
        
        let data = '';
        pythonProcess.stdout.on('data', (chunk) => {
            data += chunk.toString();
        });
        
        pythonProcess.stderr.on('data', (err) => {
            console.error('Habit Tracker Error:', err.toString());
        });

        pythonProcess.on('error', (err) => {
            console.error('Failed to spawn python process:', err);
            resolve('Error: Failed to run habit tracker. Is Python installed?');
        });

        pythonProcess.on('close', (code) => {
            if (code !== 0) {
                console.warn(`Habit tracker process exited with code ${code}`);
                resolve(data || 'No stats available.'); 
            } else {
                resolve(data);
            }
        });
    });
});

ipcMain.on('open-analytics', () => {
    console.log('[IPC] open-analytics event received');
    if (analyticsWindow) {
        console.log('[IPC] Analytics window already exists, focusing...');
        analyticsWindow.focus();
        return;
    }
    analyticsWindow = new BrowserWindow({
        width: 1200,
        height: 800,
        title: 'Analytics Dashboard',
        backgroundColor: '#0a0e1a',
        show: false, // Start hidden to prevent flash
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.cjs')
        },
        autoHideMenuBar: true
    });

    analyticsWindow.once('ready-to-show', () => {
        console.log('[Main] Analytics window ready to show');
        analyticsWindow.show();
    });
    
    // The analytics window is the same app on the same origin as the main
    // window — never a separate dist/ copy, so both surfaces stay in sync.
    const target = `${DEV_SERVER_URL}/?route=analytics`;
    console.log('[IPC] Loading analytics:', target);
    analyticsWindow.loadURL(target);

    analyticsWindow.on('closed', () => {
        analyticsWindow = null;
    });
});

app.whenReady().then(async () => {
    // Auto-grant capture to our own origin so the mic/camera actually open.
    // The check handler receives the requesting origin as its 3rd argument —
    // returning true for every origin is what the old blanket handler did.
    session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
        callback(MEDIA_PERMISSIONS.has(permission));
    });

    session.defaultSession.setPermissionCheckHandler((webContents, permission, requestingOrigin) => {
        return MEDIA_PERMISSIONS.has(permission) && isOurOrigin(requestingOrigin);
    });

    // The window always loads the dev server (the same origin the app needs
    // for getUserMedia), so refuse to open rather than fall back to dist/.
    const ready = await waitForDevServer(DEV_SERVER_URL);
    if (!ready) {
        console.error(`\n[Main] No UI server at ${DEV_SERVER_URL}.`);
        console.error('[Main] `npm run gui` only opens the desktop window — the servers come from `npm run dev`.');
        console.error('[Main] Run this in another terminal, then start the GUI again:');
        console.error('\n    npm run dev\n');
        app.exit(1);
        return;
    }

    createWindow();
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

// Terminal closed / Ctrl+C in the launching terminal must not leave the window
// running headless: quit explicitly instead of relying on the default handler.
// Nothing else is spawned from here, so quitting the window ends the GUI.
for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(sig, () => {
        console.log(`[Main] ${sig} received — closing Aariya.`);
        app.quit();
    });
}

// `npm run gui` starts us through Electron's CLI wrapper, so a signal aimed at
// the launcher (terminal closed, Ctrl+C, launcher killed) can leave the real
// Electron process orphaned and still showing a window. Reparenting to launchd
// (ppid → 1) is the observable proof the launcher is gone, and it catches the
// cases we cannot intercept with a signal handler — so poll for it and quit.
// POSIX only: on Windows the console-close event already arrives, and ppid is
// not reliably reported.
const launchParentPid = process.ppid;
if (process.platform !== 'win32' && launchParentPid > 1) {
    const parentWatch = setInterval(() => {
        if (process.ppid !== launchParentPid) {
            console.log('[Main] Launcher process is gone — closing Aariya.');
            clearInterval(parentWatch);
            app.quit();
        }
    }, 1000);
}

app.on('activate', () => {
    if (mainWindow === null) {
        createWindow();
    }
});
