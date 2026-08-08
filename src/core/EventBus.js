// src/core/EventBus.js
/**
 * EventBus - Simple Pub/Sub for decoupled system communication.
 */
class EventBus {
  constructor() {
    this.listeners = new Map();
  }

  /**
   * Subscribes to an event.
   * @param {string} event 
   * @param {Function} callback 
   * @returns {Function} Unsubscribe function
   */
  subscribe(event, callback) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event).add(callback);
    return () => this.unsubscribe(event, callback);
  }

  /**
   * Unsubscribes from an event.
   * @param {string} event 
   * @param {Function} callback 
   */
  unsubscribe(event, callback) {
    if (this.listeners.has(event)) {
      this.listeners.get(event).delete(callback);
    }
  }

  /**
   * Publishes data to all subscribers of an event.
   * @param {string} event 
   * @param {any} data 
   */
  publish(event, data) {
    if (this.listeners.has(event)) {
      this.listeners.get(event).forEach(cb => {
        try {
          cb(data);
        } catch (error) {
          console.error(`Error in EventBus subscriber for "${event}":`, error);
        }
      });
    }
  }
}

export const eventBus = new EventBus();
