export const schema = {
  profile: {
    name: null,
    language: "English",
    communicationStyle: "casual",
    flirtTolerance: "light",
    intimacyLevel: 1, // 0-3
    accent: "neutral" // neutral, indian, british, australian
  },

  preferences: {
    likes: [],
    dislikes: [],
    topics: []
  },

  emotional: {
    seeksReassurance: false,
    lonelinessScore: 0
  },

  context: {
    recentTopics: [],
    mood: "neutral",
    energy: "medium"
  },

  safety: {
    dependencyRisk: "low",
    romanticAttempts: 0
  }
};
