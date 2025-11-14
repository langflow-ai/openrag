"use client";

import { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";

import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  ChevronDown,
  Filter,
  Search,
  X,
  Loader2,
  Plus,
  Save,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface KnowledgeFilter {
  id: string;
  name: string;
  description: string;
  query_data: string;
  owner: string;
  created_at: string;
  updated_at: string;
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
}

interface KnowledgeFilterDropdownProps {
  selectedFilter: KnowledgeFilter | null;
  onFilterSelect: (filter: KnowledgeFilter | null) => void;
}

export function KnowledgeFilterDropdown({
  selectedFilter,
  onFilterSelect,
}: KnowledgeFilterDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [filters, setFilters] = useState<KnowledgeFilter[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const loadFilters = async (query = "") => {
    setLoading(true);
    try {
      const response = await fetch("/api/knowledge-filter/search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query,
          limit: 20, // Limit for dropdown
        }),
      });

      const result = await response.json();
      if (response.ok && result.success) {
        setFilters(result.filters);
      } else {
        console.error("Failed to load knowledge filters:", result.error);
        setFilters([]);
      }
    } catch (error) {
      console.error("Error loading knowledge filters:", error);
      setFilters([]);
    } finally {
      setLoading(false);
    }
  };

  const deleteFilter = async (filterId: string, e: React.MouseEvent) => {
    e.stopPropagation();

    try {
      const response = await fetch(`/api/knowledge-filter/${filterId}`, {
        method: "DELETE",
      });

      if (response.ok) {
        // Remove from local state
        setFilters((prev) => prev.filter((f) => f.id !== filterId));

        // If this was the selected filter, clear selection
        if (selectedFilter?.id === filterId) {
          onFilterSelect(null);
        }
      } else {
        console.error("Failed to delete knowledge filter");
      }
    } catch (error) {
      console.error("Error deleting knowledge filter:", error);
    }
  };

  const handleFilterSelect = (filter: KnowledgeFilter) => {
    onFilterSelect(filter);
    setIsOpen(false);
  };

  const handleClearFilter = () => {
    onFilterSelect(null);
    setIsOpen(false);
  };

  const handleCreateNew = () => {
    setIsOpen(false);
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

      const response = await fetch("/api/knowledge-filter", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: createName.trim(),
          description: createDescription.trim(),
          queryData: JSON.stringify(defaultFilterData),
        }),
      });

      const result = await response.json();
      if (response.ok && result.success) {
        // Create the new filter object
        const newFilter: KnowledgeFilter = {
          id: result.filter.id,
          name: createName.trim(),
          description: createDescription.trim(),
          query_data: JSON.stringify(defaultFilterData),
          owner: result.filter.owner,
          created_at: result.filter.created_at,
          updated_at: result.filter.updated_at,
        };

        // Add to local filters list
        setFilters((prev) => [newFilter, ...prev]);

        // Select the new filter
        onFilterSelect(newFilter);

        // Close modal and reset form
        setShowCreateModal(false);
        setCreateName("");
        setCreateDescription("");
      } else {
        console.error("Failed to create knowledge filter:", result.error);
      }
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

  const getFilterSummary = (filter: KnowledgeFilter): string => {
    try {
      const parsed = JSON.parse(filter.query_data) as ParsedQueryData;
      const parts = [];

      if (parsed.query) parts.push(`"${parsed.query}"`);
      if (parsed.filters.data_sources.length > 0)
        parts.push(`${parsed.filters.data_sources.length} sources`);
      if (parsed.filters.document_types.length > 0)
        parts.push(`${parsed.filters.document_types.length} types`);
      if (parsed.filters.owners.length > 0)
        parts.push(`${parsed.filters.owners.length} owners`);

      return parts.join(" • ") || "No filters";
    } catch {
      return "Invalid filter";
    }
  };

  useEffect(() => {
    if (isOpen) {
      loadFilters();
    }
  }, [isOpen]);

  useEffect(() => {
    const timeoutId = setTimeout(() => {
      if (isOpen) {
        loadFilters(searchQuery);
      }
    }, 300);

    return () => clearTimeout(timeoutId);
  }, [searchQuery, isOpen]);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className="relative" ref={dropdownRef}>
      <Button
        variant={selectedFilter ? "default" : "outline"}
        size="sm"
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          "flex items-center gap-2 h-8 px-3",
          selectedFilter
            ? "hover:bg-primary hover:text-primary-foreground"
            : "hover:bg-transparent hover:text-foreground hover:border-border",
        )}
      >
        <Filter className="h-3 w-3" />
        {selectedFilter ? (
          <span className="max-w-32 truncate">{selectedFilter.name}</span>
        ) : (
          <span>All Knowledge</span>
        )}
        <ChevronDown
          className={cn("h-3 w-3 transition-transform", isOpen && "rotate-180")}
        />
      </Button>

      {isOpen && (
        <Card className="absolute right-0 top-full mt-1 w-80 max-h-96 overflow-hidden z-50 shadow-lg border-border/50 bg-card/95 backdrop-blur-sm">
          <CardContent className="p-0">
            {/* Search Header */}
            <div className="p-3 border-b border-border/50">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-3 w-3 text-muted-foreground" />
                <Input
                  placeholder="Search filters..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9 h-8 text-sm"
                />
              </div>
            </div>

            {/* Filter List */}
            <div className="max-h-64 overflow-y-auto">
              {/* Clear filter option */}
              <div
                onClick={handleClearFilter}
                className={cn(
                  "flex items-center gap-3 p-3 hover:bg-accent hover:text-accent-foreground cursor-pointer border-b border-border/30 transition-colors",
                  !selectedFilter && "bg-accent text-accent-foreground",
                )}
              >
                <div className="flex items-center gap-2 flex-1">
                  <Filter className="h-4 w-4 text-muted-foreground" />
                  <div>
                    <div className="text-sm font-medium">All Knowledge</div>
                    <div className="text-xs text-muted-foreground">
                      No filters applied
                    </div>
                  </div>
                </div>
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
                      "flex items-center gap-3 p-3 hover:bg-accent hover:text-accent-foreground cursor-pointer group transition-colors",
                      selectedFilter?.id === filter.id &&
                        "bg-accent text-accent-foreground",
                    )}
                  >
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <Filter className="h-4 w-4 text-muted-foreground group-hover:text-accent-foreground flex-shrink-0" />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium truncate group-hover:text-accent-foreground">
                          {filter.name}
                        </div>
                        <div className="text-xs text-muted-foreground group-hover:text-accent-foreground/70 truncate">
                          {getFilterSummary(filter)}
                        </div>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => deleteFilter(filter.id, e)}
                      className="opacity-0 group-hover:opacity-100 h-6 w-6 p-0 bg-transparent hover:bg-gray-700 hover:text-white transition-all duration-200 border border-transparent hover:border-gray-600"
                    >
                      <X className="h-3 w-3 text-gray-400 hover:text-white" />
                    </Button>
                  </div>
                ))
              )}
            </div>

            {/* Create New Filter Option */}
            <div className="border-t border-border/50">
              <div
                onClick={handleCreateNew}
                className="flex items-center gap-3 p-3 hover:bg-accent hover:text-accent-foreground cursor-pointer transition-colors"
              >
                <Plus className="h-4 w-4 text-green-500" />
                <div>
                  <div className="text-sm font-medium text-green-600">
                    Create New Filter
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Save current search as filter
                  </div>
                </div>
              </div>
            </div>

            {/* Selected Filter Details */}
            {selectedFilter && (
              <div className="border-t border-border/50 p-3 bg-muted/20">
                <div className="text-xs text-muted-foreground">
                  <strong>Selected:</strong> {selectedFilter.name}
                </div>
                {selectedFilter.description && (
                  <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                    {selectedFilter.description}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Create Filter Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card border border-border rounded-lg p-6 w-full max-w-md mx-4">
            <h3 className="text-lg font-semibold mb-4">
              Create New Knowledge Filter
            </h3>

            <div className="space-y-4">
              <div>
                <Label htmlFor="filter-name" className="font-medium">
                  Name <span className="text-red-400">*</span>
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
                <Label htmlFor="filter-description" className="font-medium">
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

            <div className="flex justify-end gap-2 mt-6">
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
          </div>
        </div>
      )}
    </div>
  );
}
