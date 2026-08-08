export function detectFatigue(text) {
  const words = ["tired", "sleepy", "exhausted", "done", "draining", "burnout", "fatigued"];
  if (words.some(w => text.toLowerCase().includes(w))) return true;
  
  // Very short replies often indicate low energy, but check context (usually < 6 chars)
  // We'll trust the keyword match more for now to avoid false positives on "Yes" or "No".
  // Keeping the length check conservative or optional as per request logic:
  if (text.length < 6 && text.length > 0) return true; // "k", "yeah", "tired"
  
  return false;
}

export function shortenResponse(text) {
  // Take only the first sentence to be kinder/simpler
  const parts = text.split(".");
  if (parts.length > 0) {
      return parts[0] + ".";
  }
  return text;
}
