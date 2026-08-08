// src/core/wsClient.ts
import { encode, decode } from '@msgpack/msgpack';

interface WSMessage {
  [key: string]: any;
}

/**
 * WebSocket Client with msgpack encoding and batching
 * 
 * Features:
 * - Batches messages at configurable rate (default 10 Hz)
 * - Uses msgpack for ~40% less CPU vs JSON
 * - Automatic reconnection
 * - Event-driven architecture
 */
class WSClient {
  private ws: WebSocket | null = null;
  private buffer: WSMessage[] = [];
  private batchIntervalId: number | null = null;
  private rateHz: number = 10;
  private url: string = '';
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 5;
  private reconnectDelay: number = 1000;
  private messageHandlers: Map<string, (data: any) => void> = new Map();
  
  constructor() {
    console.log('[WS Client] Initialized');
  }
  
  connect(url: string, rateHz: number = 10): Promise<void> {
    this.url = url;
    this.rateHz = rateHz;
    
    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(url);
        
        this.ws.onopen = () => {
          console.log('[WS Client] Connected');
          this.reconnectAttempts = 0;
          this.startBatching();
          resolve();
        };
        
        this.ws.onmessage = (event) => {
          this.handleMessage(event.data);
        };
        
        this.ws.onerror = (error) => {
          console.error('[WS Client] Error:', error);
          reject(error);
        };
        
        this.ws.onclose = () => {
          console.log('[WS Client] Disconnected');
          this.stopBatching();
          this.attemptReconnect();
        };
      } catch (error) {
        reject(error);
      }
    });
  }
  
  private async handleMessage(data: any): Promise<void> {
    try {
      let messages: any;
      
      if (data instanceof Blob) {
        const arrayBuffer = await data.arrayBuffer();
        messages = decode(new Uint8Array(arrayBuffer));
      } else if (data instanceof ArrayBuffer) {
        messages = decode(new Uint8Array(data));
      } else if (typeof data === 'string') {
        // Fallback to JSON if server sends JSON
        messages = JSON.parse(data);
      } else {
        console.warn('[WS Client] Unknown message format:', data);
        return;
      }
      
      // Handle single message or array of messages
      const messageArray = Array.isArray(messages) ? messages : [messages];
      
      for (const msg of messageArray) {
        this.dispatchMessage(msg);
      }
    } catch (error) {
      console.error('[WS Client] Failed to decode message:', error);
    }
  }
  
  private dispatchMessage(msg: any): void {
    if (msg.type && this.messageHandlers.has(msg.type)) {
      const handler = this.messageHandlers.get(msg.type);
      if (handler) {
        handler(msg);
      }
    } else {
      // Emit generic message event
      window.dispatchEvent(new CustomEvent('wsMessage', { detail: msg }));
    }
  }
  
  private attemptReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[WS Client] Max reconnection attempts reached');
      return;
    }
    
    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
    
    console.log(`[WS Client] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
    
    setTimeout(() => {
      this.connect(this.url, this.rateHz).catch((error) => {
        console.error('[WS Client] Reconnection failed:', error);
      });
    }, delay);
  }
  
  private startBatching(): void {
    if (this.batchIntervalId !== null) return;
    
    const interval = 1000 / this.rateHz;
    
    this.batchIntervalId = window.setInterval(() => {
      this.flush();
    }, interval);
    
    console.log(`[WS Client] Batching started at ${this.rateHz} Hz`);
  }
  
  private stopBatching(): void {
    if (this.batchIntervalId !== null) {
      clearInterval(this.batchIntervalId);
      this.batchIntervalId = null;
    }
  }
  
  private flush(): void {
    if (this.buffer.length === 0) return;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    
    try {
      const encoded = encode(this.buffer);
      this.ws.send(encoded);
      this.buffer = [];
    } catch (error) {
      console.error('[WS Client] Failed to send batch:', error);
    }
  }
  
  /**
   * Queue a message to be sent in the next batch
   */
  queue(message: WSMessage): void {
    this.buffer.push(message);
  }
  
  /**
   * Send a message immediately (bypasses batching)
   */
  sendImmediate(message: WSMessage): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('[WS Client] Cannot send, not connected');
      return;
    }
    
    try {
      const encoded = encode(message);
      this.ws.send(encoded);
    } catch (error) {
      console.error('[WS Client] Failed to send immediate message:', error);
    }
  }
  
  /**
   * Register a handler for a specific message type
   */
  on(type: string, handler: (data: any) => void): void {
    this.messageHandlers.set(type, handler);
  }
  
  /**
   * Unregister a handler
   */
  off(type: string): void {
    this.messageHandlers.delete(type);
  }
  
  disconnect(): void {
    this.stopBatching();
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.buffer = [];
    console.log('[WS Client] Disconnected');
  }
  
  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }
  
  getBufferSize(): number {
    return this.buffer.length;
  }
  
  setRateHz(hz: number): void {
    this.rateHz = hz;
    if (this.batchIntervalId !== null) {
      this.stopBatching();
      this.startBatching();
    }
  }
}

export const wsClient = new WSClient();
