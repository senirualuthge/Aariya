/**
 * src/systems/safety/ContentFilter.js
 * Multi-layer safety system for content moderation.
 */

class ContentFilter {
  constructor() {
    this.rules = {
      profanity: /\b(badword1|badword2|offensive)\b/gi, // Placeholders
      personalInfo: /\b\d{3}-\\d{2}-\\d{4}\b/g, // SSN pattern
      urls: /(https?:\/\/[^\s]+)/g
    };
  }

  /**
   * Moderates content by checking against rules and (optionally) AI.
   * @param {string} content 
   * @param {string} type 'user' | 'bot'
   * @returns {Promise<Object>} { safe, issues, sanitized }
   */
  async moderate(content, type = 'user') {
    if (!content) return { safe: true, issues: [], sanitized: "" };

    const issues = [];
    
    // 1. Rule-based checks (Immediate)
    for (const [rule, pattern] of Object.entries(this.rules)) {
      if (pattern.test(content)) {
        issues.push({ type: rule, severity: 'medium' });
      }
    }
    
    // 2. Length-based heuristic for 'user' input
    if (type === 'user' && content.length > 500) {
      issues.push({ type: 'length_limit', severity: 'low' });
    }

    // 3. AI-based moderation (Simulation)
    // In a real app, this calls an external moderation API.
    const isSafeAI = true; 
    
    return {
      safe: issues.filter(i => i.severity === 'high').length === 0 && isSafeAI,
      issues,
      sanitized: this.sanitize(content, issues)
    };
  }

  /**
   * Redacts sensitive information from the content.
   */
  sanitize(content, issues) {
    let sanitized = content;
    
    for (const issue of issues) {
      if (issue.type === 'personalInfo') {
        sanitized = sanitized.replace(this.rules.personalInfo, '[REDACTED]');
      }
      // Add more sanitization rules as needed
    }
    
    return sanitized;
  }
}

export const contentFilter = new ContentFilter();
