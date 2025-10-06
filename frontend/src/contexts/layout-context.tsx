"use client";

import { createContext, useContext } from "react";

interface LayoutContextType {
  headerHeight: number;
  totalTopOffset: number;
}

const LayoutContext = createContext<LayoutContextType | undefined>(undefined);

export function useLayout() {
  const context = useContext(LayoutContext);
  if (context === undefined) {
    throw new Error("useLayout must be used within a LayoutProvider");
  }
  return context;
}

export function LayoutProvider({
  children,
  headerHeight,
  totalTopOffset
}: {
  children: React.ReactNode;
  headerHeight: number;
  totalTopOffset: number;
}) {
  return (
    <LayoutContext.Provider value={{ headerHeight, totalTopOffset }}>
      {children}
    </LayoutContext.Provider>
  );
}