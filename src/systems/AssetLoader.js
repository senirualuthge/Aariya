/**
 * src/systems/AssetLoader.js
 * Handles lazy loading and caching of heavy assets (voices, models, etc.).
 */

class AssetLoader {
  constructor() {
    this.cache = new Map();
    this.loading = new Map();
  }

  /**
   * Dynamically imports a voice preset.
   * @param {string} voiceId 
   * @returns {Promise<Object>} The voice module
   */
  async loadVoice(voiceId) {
    if (this.cache.has(voiceId)) {
      return this.cache.get(voiceId);
    }

    if (this.loading.has(voiceId)) {
      return this.loading.get(voiceId);
    }

    // SIMULATION of dynamic import
    // In a real Vite app: import(`./voice/presets/${voiceId}.js`)
    console.log(`[AssetLoader] Loading voice: ${voiceId}...`);
    
    const loadPromise = new Promise(resolve => {
        setTimeout(() => {
            const mockVoice = { name: voiceId, rate: 1.0, pitch: 1.0 };
            this.cache.set(voiceId, mockVoice);
            this.loading.delete(voiceId);
            resolve(mockVoice);
        }, 500);
    });

    this.loading.set(voiceId, loadPromise);
    return loadPromise;
  }

  /**
   * Preloads a list of critical assets.
   */
  preload(assets) {
    console.log(`[AssetLoader] Preloading critical assets: ${assets.join(", ")}`);
    return Promise.all(
      assets.map(asset => this.loadVoice(asset))
    );
  }
}

export const assetLoader = new AssetLoader();
