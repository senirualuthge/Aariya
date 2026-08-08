import { create } from "zustand";

export const useSignalsStore = create((set, get) => ({
  signals: [],
  selectedSignal: null,

  addSignal: (s) =>
    set((state) => ({
      signals: [s, ...state.signals].slice(0, 5000),
    })),

  bulkAdd: (sigs) =>
    set((state) => ({
      signals: [...sigs, ...state.signals].slice(0, 5000),
    })),

  acknowledge: (id) =>
    set((state) => ({
      signals: state.signals.map((s) =>
        s.id === id ? { ...s, status: "acknowledged" } : s
      ),
    })),

  resolve: (id) =>
    set((state) => ({
      signals: state.signals.map((s) =>
        s.id === id ? { ...s, status: "resolved" } : s
      ),
    })),

  select: (id) =>
    set({
      selectedSignal: get().signals.find((s) => s.id === id),
    }),
}));
