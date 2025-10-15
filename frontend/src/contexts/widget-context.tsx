"use client";

import { createContext, useContext, useState, useCallback, useEffect } from "react";

interface Widget {
  widget_id: string;
  prompt: string;
  user_id: string;
  created_at: string;
  has_css: boolean;
}

interface WidgetContextType {
  widgets: Widget[];
  selectedWidget: string | null;
  setSelectedWidget: (widgetId: string | null) => void;
  loadWidgets: () => Promise<void>;
  isLoading: boolean;
}

const WidgetContext = createContext<WidgetContextType | undefined>(undefined);

export function WidgetProvider({ children }: { children: React.ReactNode }) {
  const [widgets, setWidgets] = useState<Widget[]>([]);
  const [selectedWidget, setSelectedWidget] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const loadWidgets = useCallback(async () => {
    try {
      setIsLoading(true);
      const response = await fetch("/api/widgets");
      if (!response.ok) throw new Error("Failed to load widgets");
      const data = await response.json();
      setWidgets(data.widgets || []);
    } catch (error) {
      console.error("Failed to load widgets:", error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  return (
    <WidgetContext.Provider
      value={{
        widgets,
        selectedWidget,
        setSelectedWidget,
        loadWidgets,
        isLoading,
      }}
    >
      {children}
    </WidgetContext.Provider>
  );
}

export function useWidget() {
  const context = useContext(WidgetContext);
  if (context === undefined) {
    throw new Error("useWidget must be used within a WidgetProvider");
  }
  return context;
}
