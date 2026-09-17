/**
 * src/systems/memory/MemoryManager.js
 * Tiered Memory System: Short-term (RAM) and Long-term (IndexedDB).
 */

class MemoryManager {
  constructor() {
    this.shortTerm = new Map(); // Recent interactions
    this.contextWindow = []; // Rolling window of last 3 turns
    this.currentTopic = "general";
    this.workingMemory = new Map(); // Current session context
    this.longTerm = null; // IndexedDB reference
    this.dbName = 'AIGirlMemory';
    this.initDB();
  }

  async initDB() {
    if (typeof window === 'undefined' || !window.indexedDB) return;

    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this.dbName, 1);
      
      request.onupgradeneeded = (e) => {
        const db = e.target.result;
        
        if (!db.objectStoreNames.contains('conversations')) {
          const store = db.createObjectStore('conversations', { 
            keyPath: 'id', 
            autoIncrement: true 
          });
          store.createIndex('timestamp', 'timestamp', { unique: false });
          store.createIndex('emotion', 'emotion', { unique: false });
        }
        
        if (!db.objectStoreNames.contains('preferences')) {
          db.createObjectStore('preferences', { keyPath: 'key' });
        }
      };
      
      request.onsuccess = (e) => {
        this.longTerm = e.target.result;
        console.log("[Memory] IndexedDB initialized successfully");
        resolve();
      };

      request.onerror = (e) => {
        console.error("[Memory] IndexedDB error:", e.target.error);
        reject(e.target.error);
      };
    });
  }

  async store(data, tier = 'short') {
    const entry = {
      ...data,
      timestamp: Date.now(),
      id: data.id || crypto.randomUUID()
    };

    switch(tier) {
      case 'short':
        this.shortTerm.set(entry.id, entry);
        this.pruneShortTerm();
        break;
      case 'long':
        if (this.longTerm) {
          await this.storeInIndexedDB(entry);
        } else {
          // Fallback to short-term if DB not ready
          this.shortTerm.set(entry.id, entry);
        }
        break;
    }
    
    return entry;
  }

  async storeInIndexedDB(entry) {
    return new Promise((resolve, reject) => {
      if (!this.longTerm) return reject("Database not initialized");
      
      const tx = this.longTerm.transaction(['conversations'], 'readwrite');
      const store = tx.objectStore('conversations');
      const request = store.add(entry);
      
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  pruneShortTerm() {
    const thirtyMinAgo = Date.now() - (30 * 60 * 1000);
    for (const [id, entry] of this.shortTerm) {
      if (entry.timestamp < thirtyMinAgo) {
        this.shortTerm.delete(id);
      }
    }
  }

  async recall(query) {
    // Basic search implementation for now
    console.log(`[Memory] Recalling for query: ${query}`);
    return Array.from(this.shortTerm.values()).slice(-5);
  }

  // --- CONTEXT MANAGEMENT (Read.txt Requirement) ---

  addToContext(role, text, emotion = 'neutral') {
    // 1. Add to rolling window
    this.contextWindow.push({ role, text, emotion, timestamp: Date.now() });
    
    // Keep only last 3 turns (User + AI pairs, roughly 6 messages)
    if (this.contextWindow.length > 6) {
        this.contextWindow.shift();
    }

    // 2. Update Topic
    this.updateTopic(text);
  }

  getContext() {
    // Background mood is derived from the emotions actually recorded on
    // recent turns (majority vote) — never hardcoded.
    const counts = {};
    for (const turn of this.contextWindow) {
      if (turn.emotion) counts[turn.emotion] = (counts[turn.emotion] || 0) + 1;
    }
    const dominant = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
    return {
        recentTurns: this.contextWindow,
        topic: this.currentTopic,
        bgMood: dominant ? dominant[0] : "neutral"
    };
  }

  updateTopic(text) {
    const lower = text.toLowerCase();
    // Lexical topic classifier — real keyword rules over the user's text.
    if (lower.includes("tech") || lower.includes("code") || lower.includes("ai")) this.currentTopic = "technology";
    else if (lower.includes("weather") || lower.includes("rain") || lower.includes("sun")) this.currentTopic = "weather";
    else if (lower.includes("love") || lower.includes("hate") || lower.includes("fear")) this.currentTopic = "feelings";
    // Keep existing topic if no strong keyword found
  }
}

export const memoryManager = new MemoryManager();
