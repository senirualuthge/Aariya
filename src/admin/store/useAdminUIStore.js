import { create } from "zustand";

export const useAdminUIStore = create((set) => ({
  sidebarOpen: true,
  activePage: "overview",

  setPage: (p) => set({ activePage: p }),
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
}));
