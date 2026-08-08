/**
 * ConnectivityManager.js
 * Manages the AI's "connection" status to the outside world.
 * simulates bandwidth and checks for online status.
 */

class ConnectivityManager {
    constructor() {
        this.isOnline = true; // Default to online
        this.bandwidth = 'high'; // high, low, offline
        this.listeners = [];
        
        // Setup simple listener for browser online/offline events if valid
        if (typeof window !== 'undefined') {
            window.addEventListener('online', () => this.setOnline(true));
            window.addEventListener('offline', () => this.setOnline(false));
            this.isOnline = navigator.onLine;
        }
    }

    setOnline(status) {
        this.isOnline = status;
        this.bandwidth = status ? 'high' : 'offline';
        this.notifyListeners();
        console.log(`[Connectivity] Status: ${status ? 'Online' : 'Offline'}`);
    }

    subscribe(callback) {
        this.listeners.push(callback);
        return () => this.listeners = this.listeners.filter(cb => cb !== callback);
    }

    notifyListeners() {
        this.listeners.forEach(cb => cb({ isOnline: this.isOnline, bandwidth: this.bandwidth }));
    }

    /**
     * Checks if a high-bandwidth feature (like video search) is allowed
     */
    canUseFeature(cost = 'low') {
        if (!this.isOnline) return false;
        if (this.bandwidth === 'low' && cost === 'high') return false;
        return true;
    }
}

export const connectivityManager = new ConnectivityManager();
