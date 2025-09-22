"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Filter, Loader2, Plus, Save } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useGetFiltersSearchQuery,
  type KnowledgeFilter,
} from "@/src/app/api/queries/useGetFiltersSearchQuery";
import { useCreateFilter } from "@/src/app/api/mutations/useCreateFilter";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface ParsedQueryData {
  query: string;
  filters: {
    data_sources: string[];
    document_types: string[];
    owners: string[];
  };
  limit: number;
  scoreThreshold: number;
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
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [creating, setCreating] = useState(false);

  const { data, isFetching: loading } = useGetFiltersSearchQuery(
    searchQuery,
    20
  );

  const filters = data || [];

  const createFilterMutation = useCreateFilter();

  const handleFilterSelect = (filter: KnowledgeFilter) => {
    onFilterSelect(filter);
  };

  const handleCreateNew = () => {
    setShowCreateModal(true);
  };

  const handleCreateFilter = async () => {
    if (!createName.trim()) return;

    setCreating(true);
    try {
      // Create a basic filter with wildcards (match everything by default)
      const defaultFilterData = {
        query: "",
        filters: {
          data_sources: ["*"],
          document_types: ["*"],
          owners: ["*"],
        },
        limit: 10,
        scoreThreshold: 0,
      };

      const result = await createFilterMutation.mutateAsync({
        name: createName.trim(),
        description: createDescription.trim(),
        queryData: JSON.stringify(defaultFilterData),
      });

      // Select the new filter from API response
      onFilterSelect(result.filter);

      // Close modal and reset form
      setShowCreateModal(false);
      setCreateName("");
      setCreateDescription("");
    } catch (error) {
      console.error("Error creating knowledge filter:", error);
    } finally {
      setCreating(false);
    }
  };

  const handleCancelCreate = () => {
    setShowCreateModal(false);
    setCreateName("");
    setCreateDescription("");
  };

  const parseQueryData = (queryData: string): ParsedQueryData => {
    return JSON.parse(queryData) as ParsedQueryData;
  };

  return (
    <>
      <div className="flex flex-col items-center gap-1 px-3 !mb-12 mt-0 h-full overflow-y-auto">
        <div className="flex items-center w-full justify-between pl-3">
          <div className="text-sm font-medium text-muted-foreground">
            Knowledge Filters
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleCreateNew}
            title="Create New Filter"
            className="h-8 px-3"
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
          <div className="p-4 text-center text-sm text-muted-foreground">
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
                  <Filter className="h-4 w-4" />
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
                      const dataSources =
                        parseQueryData(filter.query_data).filters.data_sources;
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
      {/* Create Filter Dialog */}
      <Dialog open={showCreateModal} onOpenChange={setShowCreateModal}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create New Knowledge Filter</DialogTitle>
            <DialogDescription>
              Save a reusable filter to quickly scope searches across your
              knowledge base.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2 space-y-2">
            <div>
              <Label htmlFor="filter-name" className="font-medium mb-2 gap-1">
                Name<span className="text-red-400">*</span>
              </Label>
              <Input
                id="filter-name"
                type="text"
                placeholder="Enter filter name"
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="filter-description" className="font-medium mb-2">
                Description (optional)
              </Label>
              <Textarea
                id="filter-description"
                placeholder="Brief description of this filter"
                value={createDescription}
                onChange={(e) => setCreateDescription(e.target.value)}
                className="mt-1"
                rows={3}
              />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={handleCancelCreate}
              disabled={creating}
            >
              Cancel
            </Button>
            <Button
              onClick={handleCreateFilter}
              disabled={!createName.trim() || creating}
              className="flex items-center gap-2"
            >
              {creating ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Creating...
                </>
              ) : (
                <>
                  <Save className="h-4 w-4" />
                  Create Filter
                </>
              )}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
