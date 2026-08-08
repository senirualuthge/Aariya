const userProfiles = new Map();

export function saveProfile(userId, profile) {
  userProfiles.set(userId, profile);
}

export function loadProfile(userId) {
  return userProfiles.get(userId) || getDefaultProfile(userId);
}

export function getDefaultProfile(userId) {
  return {
    userId,
    baselineTrust: 0.5,
    emotionalBaseline: 0.5,
    volatility: 0,
    thresholds: {
      trustDrop: -0.2,
      emotionDrop: -0.2,
      contradictionHigh: 0.5
    },
    lastUpdated: Date.now()
  };
}
