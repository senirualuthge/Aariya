/* global process */
import { app, BrowserWindow, session, ipcMain } from 'electron';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';
import { spawn } from 'child_process';
import { readBuildSummary } from './build-summary.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let mainWindow;
let analyticsWindow;
let backendProcess = null;

function startBackendServer() {
    console.log('[Main] Starting Python backend server...');
    const isWin = process.platform === 'win32';
    const uvicornPath = isWin 
        ? path.join(__dirname, 'venv', 'Scripts', 'uvicorn.exe') 
        : path.join(__dirname, 'venv', 'bin', 'uvicorn');

    backendProcess = spawn(uvicornPath, ['server.main:app', '--port', '8000', '--reload'], {
        cwd: __dirname
    });

    backendProcess.stdout.on('data', (data) => console.log(`[Backend]: ${data}`.trim()));
    backendProcess.stderr.on('data', (data) => console.error(`[Backend]: ${data}`.trim()));
    
    backendProcess.on('error', (err) => {
        console.error('[Backend Failed]:', err);
    });
}

async function waitForVite(url, retries = 15, delayMs = 500) {
    for (let i = 0; i < retries; i++) {
        try {
            await fetch(url);
            return true;
        } catch {
            console.log(`[Main] Vite not ready yet, retrying (${i + 1}/${retries})...`);
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

    const isDev = !app.isPackaged;

    if (isDev) {
        const viteUrl = 'http://127.0.0.1:5173';
        console.log('[Main] Dev mode: waiting for Vite dev server...');
        const ready = await waitForVite(viteUrl);
        if (ready) {
            console.log('[Main] Vite ready — loading dev URL');
            mainWindow.loadURL(viteUrl);
        } else {
            console.warn('[Main] Vite not found — falling back to dist/');
            mainWindow.loadFile(path.join(__dirname, 'dist', 'index.html'));
        }
        // DevTools disabled — press Cmd+Option+I to open manually if needed
    } else {
        console.log('[Main] Production mode: loading from dist/');
        mainWindow.loadFile(path.join(__dirname, 'dist', 'index.html'));
    }
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
    
    if (mainWindow) {
        const currentUrl = mainWindow.webContents.getURL();
        console.log('[IPC] Main window current URL:', currentUrl);
        
        // Handle dev server (any localhost or 127.0.0.1)
        if (currentUrl.includes('localhost:') || currentUrl.includes('127.0.0.1:')) {
            try {
                const baseUrl = new URL(currentUrl).origin;
                const target = `${baseUrl}/?route=analytics`;
                console.log('[IPC] Loading dev analytics:', target);
                analyticsWindow.loadURL(target);
            } catch (e) {
                console.error('[IPC] Failed to parse URL, falling back to dist:', e);
                analyticsWindow.loadFile(path.join(__dirname, 'dist', 'index.html'), { query: { route: 'analytics' } });
            }
        } else {
            const targetPath = path.join(__dirname, 'dist', 'index.html');
            console.log('[IPC] Loading production analytics from:', targetPath);
            analyticsWindow.loadFile(targetPath, { query: { route: 'analytics' } });
        }
    } else {
        const isDev = !app.isPackaged;
        console.log('[IPC] No main window, isDev:', isDev);
        if (isDev) {
            analyticsWindow.loadURL('http://127.0.0.1:5173/?route=analytics');
        } else {
            analyticsWindow.loadFile(path.join(__dirname, 'dist', 'index.html'), { query: { route: 'analytics' } });
        }
    }

    analyticsWindow.on('closed', () => {
        analyticsWindow = null;
    });
});

app.whenReady().then(async () => {
    // Handle permissions automatically
    session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
        const allowedPermissions = ['microphone', 'camera', 'media'];
        if (allowedPermissions.includes(permission)) {
            callback(true);
        } else {
            callback(false);
        }
    });

    session.defaultSession.setPermissionCheckHandler((webContents, permission) => {
        const allowedPermissions = ['microphone', 'camera', 'media'];
        return allowedPermissions.includes(permission);
    });

    // Automatically start Python backend
    startBackendServer();

    createWindow();
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

app.on('will-quit', () => {
    if (backendProcess) {
        console.log('[Main] Terminating Python backend server...');
        backendProcess.kill();
    }
});

app.on('activate', () => {
    if (mainWindow === null) {
        createWindow();
    }
});
