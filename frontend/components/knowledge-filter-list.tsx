"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Loader2, Plus, X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useGetFiltersSearchQuery,
  type KnowledgeFilter,
} from "@/src/app/api/queries/useGetFiltersSearchQuery";
import { useKnowledgeFilter } from "@/src/contexts/knowledge-filter-context";
import {
  FilterColor,
  IconKey,
  iconKeyToComponent,
} from "./filter-icon-popover";
import { filterAccentClasses } from "./knowledge-filter-panel";

interface ParsedQueryData {
  query: string;
  filters: {
    data_sources: string[];
    document_types: string[];
    owners: string[];
  };
  limit: number;
  scoreThreshold: number;
  color?: FilterColor;
  icon?: IconKey;
}

interface KnowledgeFilterListProps {
  selectedFilter: KnowledgeFilter | null;
  onFilterSelect: (filter: KnowledgeFilter | null) => void;
}

export function KnowledgeFilterList({
  selectedFilter,
  onFilterSelect,
}: KnowledgeFilterListProps) {
  const [searchQuery] = useState("");
  const { startCreateMode } = useKnowledgeFilter();

  const { data, isFetching: loading } = useGetFiltersSearchQuery(
    searchQuery,
    20
  );

  const filters = data || [];

  const handleFilterSelect = (filter: KnowledgeFilter) => {
    if (filter.id === selectedFilter?.id) {
      onFilterSelect(null);
      return;
    }
    onFilterSelect(filter);
  };

  const handleCreateNew = () => {
    startCreateMode();
  };

  const parseQueryData = (queryData: string): ParsedQueryData => {
    return JSON.parse(queryData) as ParsedQueryData;
  };

  return (
    <>
      <div className="flex flex-col gap-1 px-3 !mb-12 mt-0 h-full overflow-y-auto">
        <div className="flex items-center w-full justify-between pl-3">
          <div className="text-sm font-medium text-muted-foreground">
            Knowledge Filters
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleCreateNew}
            title="Create New Filter"
            className="h-8 px-3 text-muted-foreground"
          >
            <Plus className="h-3 w-3" />
          </Button>
        </div>
        {loading ? (
          <div className="flex items-center justify-center p-4">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="ml-2 text-sm text-muted-foreground">
              Loading...
            </span>
          </div>
        ) : filters.length === 0 ? (
          <div className="py-2 px-4 text-sm text-muted-foreground">
            {searchQuery ? "No filters found" : "No saved filters"}
          </div>
        ) : (
          filters.map((filter) => (
            <div
              key={filter.id}
              onClick={() => handleFilterSelect(filter)}
              className={cn(
                "flex items-center gap-3 px-3 py-2 w-full rounded-lg hover:bg-accent hover:text-accent-foreground cursor-pointer group transition-colors",
                selectedFilter?.id === filter.id &&
                  "active bg-accent text-accent-foreground"
              )}
            >
              <div className="flex flex-col gap-1 flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  {(() => {
                    const parsed = parseQueryData(filter.query_data);
                    const Icon = iconKeyToComponent(parsed.icon);
                    return (
                      <div
                        className={cn(
                          "flex items-center justify-center w-5 h-5 rounded transition-colors",
                          filterAccentClasses[parsed.color || ""],
                          parsed.color === "zinc" &&
                            "group-hover:bg-background group-[.active]:bg-background"
                        )}
                      >
                        {Icon && <Icon className="h-3 w-3" />}
                      </div>
                    );
                  })()}
                  <div className="text-sm font-medium truncate group-hover:text-accent-foreground">
                    {filter.name}
                  </div>
                </div>
                {filter.description && (
                  <div className="text-xs text-muted-foreground line-clamp-2">
                    {filter.description}
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <div className="text-xs text-muted-foreground">
                    {new Date(filter.created_at).toLocaleDateString(undefined, {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                    })}
                  </div>
                  <span className="text-xs bg-muted text-muted-foreground px-1 py-0.5 rounded-sm group-hover:bg-background group-[.active]:bg-background transition-colors">
                    {(() => {
                      const dataSources = parseQueryData(filter.query_data)
                        .filters.data_sources;
                      if (dataSources[0] === "*") return "All sources";
                      const count = dataSources.length;
                      return `${count} ${count === 1 ? "source" : "sources"}`;
                    })()}
                  </span>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
      {/* Create flow moved to panel create mode */}
    </>
  );
}
