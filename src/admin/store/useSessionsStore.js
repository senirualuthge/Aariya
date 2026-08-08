import { create } from "zustand";

export const useSessionsStore = create((set) => ({
  sessions: {},

  upsert: (s) =>
    set((state) => ({
      sessions: { ...state.sessions, [s.sessionId]: s },
    })),

  remove: (id) =>
    set((state) => {
      const copy = { ...state.sessions };
      delete copy[id];
      return { sessions: copy };
    }),
}));
