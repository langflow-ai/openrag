"use client";

import { FilterColor, IconKey } from "@/components/filter-icon-popover";
import React, {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";

interface KnowledgeFilter {
  id: string;
  name: string;
  description: string;
  query_data: string;
  owner: string;
  created_at: string;
  updated_at: string;
}

export interface ParsedQueryData {
  query: string;
  filters: {
    data_sources: string[];
    document_types: string[];
    owners: string[];
    connector_types: string[];
  };
  limit: number;
  scoreThreshold: number;
  color: FilterColor;
  icon: IconKey;
}

interface KnowledgeFilterContextType {
  selectedFilter: KnowledgeFilter | null;
  parsedFilterData: ParsedQueryData | null;
  setSelectedFilter: (filter: KnowledgeFilter | null) => void;
  clearFilter: () => void;
  isPanelOpen: boolean;
  openPanel: () => void;
  closePanel: () => void;
  closePanelOnly: () => void;
  createMode: boolean;
  startCreateMode: () => void;
  endCreateMode: () => void;
  queryOverride: string;
  setQueryOverride: (query: string) => void;
}

const KnowledgeFilterContext = createContext<
  KnowledgeFilterContextType | undefined
>(undefined);

export function useKnowledgeFilter() {
  const context = useContext(KnowledgeFilterContext);
  if (context === undefined) {
    throw new Error(
      "useKnowledgeFilter must be used within a KnowledgeFilterProvider",
    );
  }
  return context;
}

interface KnowledgeFilterProviderProps {
  children: ReactNode;
}

export function KnowledgeFilterProvider({
  children,
}: KnowledgeFilterProviderProps) {
  const [selectedFilter, setSelectedFilterState] =
    useState<KnowledgeFilter | null>(null);
  const [parsedFilterData, setParsedFilterData] =
    useState<ParsedQueryData | null>(null);
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  const [createMode, setCreateMode] = useState(false);
  const [queryOverride, setQueryOverride] = useState("");

  const setSelectedFilter = (filter: KnowledgeFilter | null) => {
    setSelectedFilterState(filter);

    if (filter) {
      setCreateMode(false);
      try {
        const raw = JSON.parse(filter.query_data);
        // Normalize parsed data with defaults for missing fields
        // This handles filters created via API with incomplete queryData
        const parsed: ParsedQueryData = {
          query: raw.query ?? "",
          filters: {
            data_sources: raw.filters?.data_sources ?? ["*"],
            document_types: raw.filters?.document_types ?? ["*"],
            owners: raw.filters?.owners ?? ["*"],
            connector_types: raw.filters?.connector_types ?? ["*"],
          },
          limit: raw.limit ?? 10,
          scoreThreshold: raw.scoreThreshold ?? 0,
          color: raw.color ?? "zinc",
          icon: raw.icon ?? "filter",
        };
        setParsedFilterData(parsed);

        // Auto-open panel when filter is selected
        setIsPanelOpen(true);
      } catch (error) {
        console.error("Error parsing filter data:", error);
        setParsedFilterData(null);
      }
    } else {
      setParsedFilterData(null);
      setIsPanelOpen(false);
    }
  };

  const clearFilter = () => {
    setSelectedFilter(null);
  };

  const openPanel = () => {
    setIsPanelOpen(true);
  };

  const closePanel = () => {
    setCreateMode(false);
    setSelectedFilter(null); // This will also close the panel
  };

  const closePanelOnly = () => {
    setIsPanelOpen(false); // Close panel but keep filter selected
  };

  const startCreateMode = () => {
    // Initialize defaults
    setCreateMode(true);
    setSelectedFilterState(null);
    setParsedFilterData({
      query: "",
      filters: {
        data_sources: ["*"],
        document_types: ["*"],
        owners: ["*"],
        connector_types: ["*"],
      },
      limit: 10,
      scoreThreshold: 0,
      color: "amber",
      icon: "filter",
    });
    setIsPanelOpen(true);
  };

  const endCreateMode = () => {
    setCreateMode(false);
  };

  // Clear the search override when we change filters
  useEffect(() => {
    setQueryOverride("");
  }, [selectedFilter]);

  const value: KnowledgeFilterContextType = {
    selectedFilter,
    parsedFilterData,
    setSelectedFilter,
    clearFilter,
    isPanelOpen,
    openPanel,
    closePanel,
    closePanelOnly,
    createMode,
    startCreateMode,
    endCreateMode,
    queryOverride,
    setQueryOverride,
  };

  return (
    <KnowledgeFilterContext.Provider value={value}>
      {children}
    </KnowledgeFilterContext.Provider>
  );
}
