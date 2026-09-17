// Browser-safe DB module
// better-sqlite3 can ONLY run in Node.js (main process), not in browser/renderer
// This module provides a no-op fallback for browser contexts

const isBrowser = typeof window !== 'undefined';
// eslint-disable-next-line no-undef
const IS_NODE = !isBrowser && typeof process !== 'undefined' && process.versions?.node;

let dbInstance = null;

// Null-object DB for environments without SQLite (browser / failed init):
// never fabricates data — reads return empty, writes are no-ops.
const noopDB = {
    prepare: () => ({
        run: () => ({ changes: 0 }),
        get: () => null,
        all: () => [],
        bind: () => noopDB.prepare()
    }),
    exec: () => {},
    close: () => {},
    pragma: () => {},
    transaction: (fn) => fn,
};

function initDB() {
    if (isBrowser) {
        console.warn('[DB] SQLite not available in browser. Using IndexedDB via memoryManager instead.');
        return noopDB;
    }
    
    // Only runs in Node.js context (main process or CLI tools)
    try {
        if (!IS_NODE) throw new Error('Not Node');
        const req = eval('require');
        const Database = req('better-sqlite3');
        const fs = req('fs');
        const path = req('path');
        const os = req('os');
        const { fileURLToPath } = req('url');
        
        const DATA_DIR = path.join(os.homedir(), '.aariya');
        const DB_PATH = path.join(DATA_DIR, 'data.db');
        
        if (!fs.existsSync(DATA_DIR)) {
            fs.mkdirSync(DATA_DIR, { recursive: true });
        }
        
        const db = new Database(DB_PATH);
        // Resolve __dirname for CJS/ESM compatibility — use eval to avoid ESLint no-undef
        let currentDir;
        try { currentDir = eval('__dirname'); } catch {
            currentDir = path.dirname(fileURLToPath(import.meta.url));
        }
        const schemaPath = path.join(currentDir, 'schema.sql');
        if (fs.existsSync(schemaPath)) {
            const schema = fs.readFileSync(schemaPath, 'utf-8');
            db.exec(schema);
        }
        
        console.log('✅ Database initialized:', DB_PATH);
        return db;
    } catch (err) {
        console.error('[DB] Failed to initialize SQLite:', err.message);
        return noopDB;
    }
}

function getDB() {
    if (!dbInstance) {
        dbInstance = initDB();
    }
    return dbInstance;
}

const DB_PATH = isBrowser ? null : (() => {
    try {
        if (!IS_NODE) return null;
        const req = eval('require');
        const path = req('path');
        const os = req('os');
        return path.join(os.homedir(), '.aariya', 'data.db');
    } catch {
        return null;
    }
})();

export { isBrowser, initDB, getDB, DB_PATH };
