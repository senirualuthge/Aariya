const { spawn } = require('child_process');
const path = require('path');

console.log('\n🚀 Starting Aariya Desktop GUI...');
console.log('✨ Launching standalone window...\n');

// Get the electron executable path
let electronPath;
try {
    electronPath = require('electron');
} catch (err) {
    console.error('❌ Electron not found!');
    console.log('💡 Please install dependencies: npm install');
    process.exit(1);
}

// Launch Electron with the main process file
const electronProcess = spawn(electronPath, [path.join(__dirname, 'main.js')], {
    stdio: 'inherit',
    windowsHide: false
});

electronProcess.on('error', (err) => {
    console.error('❌ Failed to start Aariya GUI:', err.message);
    process.exit(1);
});

electronProcess.on('close', (code) => {
    if (code !== 0 && code !== null) {
        console.log(`\n👋 Aariya GUI closed with code ${code}`);
    } else {
        console.log('\n👋 Aariya GUI closed');
    }
    process.exit(code || 0);
});

// Handle Ctrl+C
process.on('SIGINT', () => {
    console.log('\n\n👋 Shutting down...');
    electronProcess.kill('SIGINT');
    setTimeout(() => process.exit(0), 500);
});
