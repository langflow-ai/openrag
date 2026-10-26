"use client";

import React, {
  createContext,
  type ReactNode,
  use,
  useCallback,
  useMemo,
  useState,
} from "react";
import {
  FILTER_COLORS,
  type FilterColor,
  type IconKey,
} from "@/lib/filter-constants";
import {
  applySelection,
  type DateRangeContext,
  type DateRangeValue,
  displayRangeFromSaved,
  NO_DATE_RANGE,
  parseSavedDateRange,
  type SavedDateRange,
} from "@/lib/saved-date-range";

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
    /** Saved inclusive UTC bounds on indexed_time; absent means any time. */
    created_after?: string;
    created_before?: string;
  };
  /** Calendar days + timezone the saved bounds were picked in (display only). */
  dateRangeContext?: DateRangeContext;
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
  panelMode: "filters" | "ingestion-status";
  openPanel: () => void;
  openIngestionStatusPanel: () => void;
  closePanel: () => void;
  closePanelOnly: () => void;
  createMode: boolean;
  startCreateMode: () => void;
  endCreateMode: () => void;
  queryOverride: string;
  setQueryOverride: (query: string) => void;
  /** Filenames checked in the knowledge table; seeds data_sources on create. */
  selectedSources: string[];
  setSelectedSources: (sources: string[]) => void;
  /**
   * Effective date range for the file grid: the selected filter's saved range,
   * unless the toolbar has overridden it. Overrides are temporary; they are
   * saved only when the Knowledge Filter itself is saved.
   */
  dateRange: DateRangeValue | null;
  setDateRange: (range: DateRangeValue | null) => void;
  /** Saved range of the selected filter (what the editor starts from). */
  savedDateRange: SavedDateRange;
  /**
   * UTC bounds used for retrieval. Unchanged saved ranges keep their exact
   * saved bounds in any viewer timezone; a cleared range has neither bound.
   */
  effectiveDateRange: SavedDateRange;
}

/** Saved range carried by parsed query data. */
export function savedDateRangeOf(
  parsed: ParsedQueryData | null,
): SavedDateRange {
  const createdAfter = parsed?.filters.created_after || undefined;
  const createdBefore = parsed?.filters.created_before || undefined;
  if (!createdAfter && !createdBefore) return NO_DATE_RANGE;
  return {
    ...(createdAfter && { createdAfter }),
    ...(createdBefore && { createdBefore }),
    ...(parsed?.dateRangeContext && { context: parsed.dateRangeContext }),
  };
}

const KnowledgeFilterContext = createContext<
  KnowledgeFilterContextType | undefined
>(undefined);

export function useKnowledgeFilter() {
  const context = use(KnowledgeFilterContext);
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
  const [panelMode, setPanelMode] = useState<"filters" | "ingestion-status">(
    "filters",
  );
  const [createMode, setCreateMode] = useState(false);
  const [queryOverride, setQueryOverride] = useState("");
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  // null = no toolbar override (use the saved range); NO_DATE_RANGE = "any time".
  const [dateRangeOverride, setDateRangeOverride] =
    useState<SavedDateRange | null>(null);

  const savedDateRange = useMemo(
    () => savedDateRangeOf(parsedFilterData),
    [parsedFilterData],
  );
  const effectiveDateRange = dateRangeOverride ?? savedDateRange;
  const dateRange = useMemo(
    () => displayRangeFromSaved(effectiveDateRange),
    [effectiveDateRange],
  );
  const setDateRange = (range: DateRangeValue | null) => {
    setDateRangeOverride(applySelection(effectiveDateRange, range));
  };

  const setSelectedFilter = (filter: KnowledgeFilter | null) => {
    setSelectedFilterState(filter);
    // A temporary toolbar range never outlives the filter it was set against.
    setDateRangeOverride(null);

    if (filter) {
      setCreateMode(false);
      try {
        const raw = JSON.parse(filter.query_data);
        const saved = parseSavedDateRange(raw);
        // Normalize parsed data with defaults for missing fields
        // This handles filters created via API with incomplete queryData
        const parsed: ParsedQueryData = {
          query: raw.query ?? "",
          filters: {
            data_sources: raw.filters?.data_sources ?? ["*"],
            document_types: raw.filters?.document_types ?? ["*"],
            owners: raw.filters?.owners ?? ["*"],
            connector_types: raw.filters?.connector_types ?? ["*"],
            ...(saved.createdAfter && { created_after: saved.createdAfter }),
            ...(saved.createdBefore && {
              created_before: saved.createdBefore,
            }),
          },
          ...(saved.context && { dateRangeContext: saved.context }),
          limit: raw.limit ?? 10,
          scoreThreshold: raw.scoreThreshold ?? 0,
          color: raw.color ?? "zinc",
          icon: raw.icon ?? "filter",
        };
        setParsedFilterData(parsed);

        // Auto-open panel when filter is selected
        setPanelMode("filters");
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
    setPanelMode("filters");
    setIsPanelOpen(true);
  };

  const openIngestionStatusPanel = () => {
    setPanelMode("ingestion-status");
    setIsPanelOpen(true);
  };

  const closePanel = () => {
    setCreateMode(false);
    setPanelMode("filters");
    setSelectedFilter(null); // This will also close the panel
  };

  const closePanelOnly = useCallback(() => {
    setIsPanelOpen(false); // Close panel but keep filter selected
  }, []);

  const startCreateMode = () => {
    // Initialize defaults; checked table rows pre-populate the sources filter
    setPanelMode("filters");
    setCreateMode(true);
    setSelectedFilterState(null);
    setDateRangeOverride(null);
    setParsedFilterData({
      query: "",
      filters: {
        data_sources: selectedSources.length > 0 ? [...selectedSources] : ["*"],
        document_types: ["*"],
        owners: ["*"],
        connector_types: ["*"],
        // No dates: a temporary toolbar range is never saved implicitly.
      },
      limit: 10,
      scoreThreshold: 0,
      color: FILTER_COLORS[Math.floor(Math.random() * FILTER_COLORS.length)],
      icon: "filter",
    });
    setIsPanelOpen(true);
  };

  const endCreateMode = () => {
    setCreateMode(false);
  };

  // Clear the search override when we change filters
  const [prevSelectedFilter, setPrevSelectedFilter] = useState(selectedFilter);
  if (selectedFilter !== prevSelectedFilter) {
    setPrevSelectedFilter(selectedFilter);
    setQueryOverride("");
  }

  const value: KnowledgeFilterContextType = {
    selectedFilter,
    parsedFilterData,
    setSelectedFilter,
    clearFilter,
    isPanelOpen,
    panelMode,
    openPanel,
    openIngestionStatusPanel,
    closePanel,
    closePanelOnly,
    createMode,
    startCreateMode,
    endCreateMode,
    queryOverride,
    setQueryOverride,
    selectedSources,
    setSelectedSources,
    dateRange,
    setDateRange,
    savedDateRange,
    effectiveDateRange,
  };

  return (
    <KnowledgeFilterContext.Provider value={value}>
      {children}
    </KnowledgeFilterContext.Provider>
  );
}
