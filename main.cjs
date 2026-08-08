const { app, BrowserWindow, session, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

// DEBUG
console.log('DEBUG: process.type:', process.type);
console.log('DEBUG: process.versions.electron:', process.versions.electron);

let mainWindow;
let analyticsWindow;

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1400,
        height: 900,
        title: 'Aariya AI Companion',
        backgroundColor: '#0a0e1a',
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.cjs')
        },
        autoHideMenuBar: true
    });

    // In development, we load from the Vite dev server
    mainWindow.loadURL('http://127.0.0.1:5173');

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

ipcMain.on('open-analytics', () => {
    if (analyticsWindow) {
        analyticsWindow.focus();
        return;
    }
    analyticsWindow = new BrowserWindow({
        width: 1200,
        height: 800,
        title: 'Analytics Dashboard',
        backgroundColor: '#0a0e1a',
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.cjs')
        },
        autoHideMenuBar: true
    });
    
    // Check if development or production
    const isDev = !app.isPackaged;
    if (isDev) {
        analyticsWindow.loadURL('http://127.0.0.1:5173/?route=analytics');
    } else {
        analyticsWindow.loadFile(path.join(__dirname, 'dist', 'index.html'), { query: { route: 'analytics' } });
    }

    analyticsWindow.on('closed', () => {
        analyticsWindow = null;
    });
});

// IPC Handler for Habit Tracker
ipcMain.handle('get-habit-stats', async () => {
    return new Promise((resolve, reject) => {
        // Using relative path to habit tracker
        // folder name is 'HabitTracker' (Case Sensitive check just in case, though Windows is loose)
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

if (app) {
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

        createWindow();
    });

    app.on('window-all-closed', () => {
        if (process.platform !== 'darwin') {
            app.quit();
        }
    });

    app.on('activate', () => {
        if (mainWindow === null) {
            createWindow();
        }
    });
} else {
    console.error('❌ FATAL ERROR: Electron "app" is undefined in the main process.');
    console.log('DEBUG: require("electron") evaluated to:', typeof require('electron'));
    process.exit(1);
}
