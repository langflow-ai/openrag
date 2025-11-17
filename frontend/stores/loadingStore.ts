import { create } from "zustand";

interface LoadingState {
  loading: boolean;
  setLoading: (loading: boolean) => void;
}

export const useLoadingStore = create<LoadingState>((set) => ({
  loading: false,
  setLoading: (loading) => set({ loading }),
}));
