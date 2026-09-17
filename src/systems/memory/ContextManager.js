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
   * REAL extractive summarization of the actual messages: sentences are
   * scored by word-frequency salience and the top ones are kept verbatim.
   * No LLM call is faked — when there is nothing to summarize the result
   * says so.
   */
  async generateSummary(messages) {
    console.log(`[ContextManager] Summarizing ${messages.length} messages...`);

    const texts = (messages || [])
      .map(m => (typeof m === 'string' ? m : m?.content))
      .filter(t => typeof t === 'string' && t.trim());
    if (!texts.length) return "(no conversation to summarize yet)";

    // Term frequency over the real content (minus stopwords).
    const STOP = new Set(['the','a','an','and','or','but','is','are','was','were',
      'to','of','in','on','at','it','i','you','we','they','he','she','my','your',
      'that','this','with','for','as','be','have','has','had','do','does','did',
      'not','so','if','then','than','too','very',"it's",'me','am']);
    const freq = Object.create(null);
    for (const t of texts) {
      for (const w of t.toLowerCase().match(/[a-z']+/g) || []) {
        if (!STOP.has(w) && w.length > 2) freq[w] = (freq[w] || 0) + 1;
      }
    }

    // Split into sentences, score each by normalized term salience.
    const sentences = texts.join(' ')
      .split(/(?<=[.!?])\s+/)
      .map(s => s.trim())
      .filter(s => s.length > 15);
    if (!sentences.length) return texts[0].slice(0, 200);

    const scored = sentences.map((s, idx) => {
      const words = s.toLowerCase().match(/[a-z']+/g) || [];
      const sal = words.reduce((acc, w) => acc + (freq[w] || 0), 0) /
        Math.max(1, words.length);
      return { s, sal, idx };
    });

    const KEEP = Math.min(3, Math.ceil(sentences.length / 4));
    const top = scored.sort((a, b) => b.sal - a.sal).slice(0, KEEP)
      .sort((a, b) => a.idx - b.idx);   // restore chronological order
    return top.map(x => x.s).join(' ');
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
