export function updateUserProfile(profile, sessions) {
  if (!sessions || sessions.length === 0) return profile;
  
  const last10 = sessions.slice(-10);

  const trusts = last10.map(s => s.psi || 0);
  const emotions = last10.map(s => s.ecs ? (s.ecs / 100) : 0);
  
  const avgTrust = avg(trusts);
  const avgEmotion = avg(emotions);
  const volatility = std(emotions);

  return {
    ...profile,
    baselineTrust: avgTrust,
    emotionalBaseline: avgEmotion,
    volatility,
    lastUpdated: Date.now()
  };
}

export function classifyUser(profile) {
  if (profile.volatility > 0.3) return "VOLATILE";
  if (profile.baselineTrust < 0.4) return "LOW_TRUST";
  if (profile.emotionalBaseline > 0.7) return "POSITIVE";
  return "STABLE";
}

function avg(arr) {
  if (!arr.length) return 0;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

function std(arr) {
  if (!arr.length || arr.length === 1) return 0;
  const mean = avg(arr);
  const diffs = arr.map(a => Math.pow(a - mean, 2));
  return Math.sqrt(avg(diffs));
}
