/**
 * src/systems/ai/AIQueue.js
 * Async Request Queue with simple prioritization and streaming support.
 */

class AIRequestQueue {
  constructor() {
    this.queue = [];
    this.processing = false;
    this.activeRequests = 0;
    this.maxConcurrent = 1; // Keep it low for local dev stability
  }

  /**
   * Enqueues a request and returns a promise that resolves when processing is complete.
   * @param {Object} request { messages, onChunk }
   * @param {string} priority 'high' | 'normal' | 'low'
   */
  async enqueue(request, priority = 'normal') {
    return new Promise((resolve, reject) => {
      this.queue.push({
        request,
        priority,
        resolve,
        reject,
        timestamp: Date.now()
      });
      
      // Sort by priority (higher weight = earlier processing)
      this.queue.sort((a, b) => {
        const priorityWeight = { high: 3, normal: 2, low: 1 };
        return priorityWeight[b.priority] - priorityWeight[a.priority];
      });
      
      this.processQueue();
    });
  }

  async processQueue() {
    if (this.activeRequests >= this.maxConcurrent || this.queue.length === 0) {
      return;
    }

    this.activeRequests++;
    const { request, resolve, reject } = this.queue.shift();

    try {
      console.log(`[AIQueue] Processing request with priority: ${request.priority || 'normal'}`);
      
      // SIMULATED STREAMING
      // In production, this would be a fetch with a ReadableStream
      let fullText = request.messages[request.messages.length - 1].content;
      // Mocking a response based on input
      let mockResponse = `I hear you. You said: "${fullText}"`;
      
      const chunks = mockResponse.split(" ");
      let assembledText = "";

      for (const chunk of chunks) {
        assembledText += chunk + " ";
        if (request.onChunk) {
          request.onChunk(chunk + " ");
        }
        // Artificial delay for streaming feel
        await new Promise(r => setTimeout(r, 100));
      }

      resolve(assembledText.trim());
    } catch (error) {
      console.error("[AIQueue] Error processing request:", error);
      reject(error);
    } finally {
      this.activeRequests--;
      this.processQueue(); // Check for next item
    }
  }
}

export const aiQueue = new AIRequestQueue();
