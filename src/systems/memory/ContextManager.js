/**
 * src/systems/memory/ContextManager.js
 * Manages conversation context with rolling summarization to save tokens.
 */

class ContextManager {
  constructor(maxTokens = 4000) {
    this.maxTokens = maxTokens;
    this.context = [];
    this.summaries = [];
  }

  /**
   * Adds a message to the context and triggers summarization if needed.
   * @param {Object} message { role, content }
   */
  async addMessage(message) {
    this.context.push(message);
    
    const estimatedTokens = this.estimateTokens();
    if (estimatedTokens > this.maxTokens) {
      await this.summarizeAndPrune();
    }
  }

  /**
   * Roughly estimates tokens (1 token ≈ 4 characters).
   */
  estimateTokens() {
    return this.context.reduce((acc, msg) => 
      acc + Math.ceil((msg.content?.length || 0) / 4), 0
    );
  }

  /**
   * Prunes the context by summarizing the oldest messages.
   */
  async summarizeAndPrune() {
    // Keep last 10 messages, summarize the rest
    const toSummarize = this.context.slice(0, -10);
    const toKeep = this.context.slice(-10);
    
    if (toSummarize.length > 0) {
      try {
        const summary = await this.generateSummary(toSummarize);
        this.summaries.push({
          summary,
          messageCount: toSummarize.length,
          timestamp: Date.now()
        });
      } catch (error) {
        console.error("[ContextManager] Summarization failed:", error);
      }
    }
    
    this.context = toKeep;
  }

  /**
   * Simulated summarization. In production, this calls an LLM.
   */
  async generateSummary(messages) {
    console.log(`[ContextManager] Summarizing ${messages.length} messages...`);
    
    // For now, we'll return a placeholder. 
    // In a real scenario, this would be an API call like the one in the guide.
    return "The user and Aariya discussed various topics including their feelings and current activities.";
  }

  /**
   * Returns the full context including summaries.
   */
  getFullContext() {
    return [
      ...this.summaries.map(s => ({ role: 'system', content: `Previous Context Summary: ${s.summary}` })),
      ...this.context
    ];
  }
}

export const contextManager = new ContextManager();
