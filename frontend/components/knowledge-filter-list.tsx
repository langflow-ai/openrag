"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Filter as FilterIcon,
  Loader2,
  Plus,
  X,
  Star,
  Book,
  FileText,
  Folder,
  Globe,
  Calendar,
  User,
  Users,
  Tag,
  Briefcase,
  Building2,
  Cog,
  Database,
  Cpu,
  Bot,
  MessageSquare,
  Search,
  Shield,
  Lock,
  Key,
  Link,
  Mail,
  Phone,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useGetFiltersSearchQuery,
  type KnowledgeFilter,
} from "@/src/app/api/queries/useGetFiltersSearchQuery";
import { useKnowledgeFilter } from "@/src/contexts/knowledge-filter-context";
import type { SVGProps } from "react";

const ICON_MAP = {
  Filter: FilterIcon,
  Star,
  Book,
  FileText,
  Folder,
  Globe,
  Calendar,
  User,
  Users,
  Tag,
  Briefcase,
  Building2,
  Cog,
  Database,
  Cpu,
  Bot,
  MessageSquare,
  Search,
  Shield,
  Lock,
  Key,
  Link,
  Mail,
  Phone,
} as const;

function iconKeyToComponent(key: string): React.ComponentType<SVGProps<SVGSVGElement>> {
  return (ICON_MAP as Record<string, React.ComponentType<SVGProps<SVGSVGElement>>>)[key] || FilterIcon;
}

interface ParsedQueryData {
  query: string;
  filters: {
    data_sources: string[];
    document_types: string[];
    owners: string[];
  };
  limit: number;
  scoreThreshold: number;
  color?: "zinc" | "pink" | "purple" | "indigo" | "emerald" | "amber" | "red";
  icon?: string;
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
                  "bg-accent text-accent-foreground"
              )}
            >
              <div className="flex flex-col gap-1 flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  {(() => {
                    const parsed = parseQueryData(filter.query_data);
                    const color = (parsed.color || "zinc") as
                      | "zinc"
                      | "pink"
                      | "purple"
                      | "indigo"
                      | "emerald"
                      | "amber"
                      | "red";
                    const Icon = iconKeyToComponent(parsed.icon || "Filter");
                    const colorMap = {
                      zinc: "bg-zinc-500/20 text-zinc-500",
                      pink: "bg-pink-500/20 text-pink-500",
                      purple: "bg-purple-500/20 text-purple-500",
                      indigo: "bg-indigo-500/20 text-indigo-500",
                      emerald: "bg-emerald-500/20 text-emerald-500",
                      amber: "bg-amber-500/20 text-amber-500",
                      red: "bg-red-500/20 text-red-500",
                    } as const;
                    const colorClasses = colorMap[color];
                    return (
                      <div className={`flex items-center justify-center ${colorClasses} w-5 h-5 rounded`}>
                        <Icon className="h-3 w-3" />
                      </div>
                    );
                  })()}
                  <div className="text-sm font-medium truncate group-hover:text-accent-foreground">
                    {filter.name}
                  </div>
                </div>
                {filter.description && (
                  <div className="text-xs text-muted-foreground group-hover:text-accent-foreground/70 line-clamp-2">
                    {filter.description}
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <div className="text-xs text-muted-foreground group-hover:text-accent-foreground/70">
                    {new Date(filter.created_at).toLocaleDateString(undefined, {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                    })}
                  </div>
                  <span className="text-xs bg-muted text-muted-foreground px-1 py-0.5 rounded-sm">
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
              {selectedFilter?.id === filter.id && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="px-0"
                  onClick={(e) => {
                    e.stopPropagation();
                    onFilterSelect(null);
                  }}
                >
                  <X className="h-4 w-4 flex-shrink-0 opacity-0 group-hover:opacity-100 text-muted-foreground" />
                </Button>
              )}
            </div>
          ))
        )}
      </div>
      {/* Create flow moved to panel create mode */}
    </>
  );
}
