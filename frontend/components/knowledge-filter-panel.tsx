"use client";

import { useState, useEffect } from "react";
import { X, Edit3, Save, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { MultiSelect } from "@/components/ui/multi-select";
import { Slider } from "@/components/ui/slider";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useDeleteFilter } from "@/app/api/mutations/useDeleteFilter";
import { useUpdateFilter } from "@/app/api/mutations/useUpdateFilter";
import { useGetSearchAggregations } from "@/src/app/api/queries/useGetSearchAggregations";

interface FacetBucket {
  key: string;
  count: number;
}

interface AvailableFacets {
  data_sources: FacetBucket[];
  document_types: FacetBucket[];
  owners: FacetBucket[];
  connector_types: FacetBucket[];
}

export function KnowledgeFilterPanel() {
  const {
    selectedFilter,
    parsedFilterData,
    setSelectedFilter,
    isPanelOpen,
    closePanelOnly,
  } = useKnowledgeFilter();
  const deleteFilterMutation = useDeleteFilter();
  const updateFilterMutation = useUpdateFilter();

  // Edit mode states
  const [isEditingMeta, setIsEditingMeta] = useState(false);
  const [editingName, setEditingName] = useState("");
  const [editingDescription, setEditingDescription] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  // Filter configuration states (mirror search page exactly)
  const [query, setQuery] = useState("");
  const [selectedFilters, setSelectedFilters] = useState({
    data_sources: ["*"] as string[], // Default to wildcard
    document_types: ["*"] as string[], // Default to wildcard
    owners: ["*"] as string[], // Default to wildcard
    connector_types: ["*"] as string[], // Default to wildcard
  });
  const [resultLimit, setResultLimit] = useState(10);
  const [scoreThreshold, setScoreThreshold] = useState(0);

  // Available facets (loaded from API)
  const [availableFacets, setAvailableFacets] = useState<AvailableFacets>({
    data_sources: [],
    document_types: [],
    owners: [],
    connector_types: [],
  });

  // Load current filter data into controls
  useEffect(() => {
    if (selectedFilter && parsedFilterData) {
      setQuery(parsedFilterData.query || "");

      // Set the actual filter selections from the saved knowledge filter
      const filters = parsedFilterData.filters;

      // Use the exact selections from the saved filter
      // Empty arrays mean "none selected" not "all selected"
      const processedFilters = {
        data_sources: filters.data_sources,
        document_types: filters.document_types,
        owners: filters.owners,
        connector_types: filters.connector_types || ["*"],
      };

      console.log("[DEBUG] Loading filter selections:", processedFilters);

      setSelectedFilters(processedFilters);
      setResultLimit(parsedFilterData.limit || 10);
      setScoreThreshold(parsedFilterData.scoreThreshold || 0);
      setEditingName(selectedFilter.name);
      setEditingDescription(selectedFilter.description || "");
    }
  }, [selectedFilter, parsedFilterData]);

  // Load available facets using search aggregations hook
  const { data: aggregations } = useGetSearchAggregations("*", 1, 0, {
    enabled: isPanelOpen,
    placeholderData: prev => prev,
    staleTime: 60_000,
    gcTime: 5 * 60_000,
  });

  useEffect(() => {
    if (!aggregations) return;
    const facets = {
      data_sources: aggregations.data_sources?.buckets || [],
      document_types: aggregations.document_types?.buckets || [],
      owners: aggregations.owners?.buckets || [],
      connector_types: aggregations.connector_types?.buckets || [],
    };
    setAvailableFacets(facets);
  }, [aggregations]);

  // Don't render if panel is closed or no filter selected
  if (!isPanelOpen || !selectedFilter || !parsedFilterData) return null;

  const selectAllFilters = () => {
    // Use wildcards instead of listing all specific items
    setSelectedFilters({
      data_sources: ["*"],
      document_types: ["*"],
      owners: ["*"],
      connector_types: ["*"],
    });
  };

  const clearAllFilters = () => {
    setSelectedFilters({
      data_sources: [],
      document_types: [],
      owners: [],
      connector_types: [],
    });
  };

  const handleEditMeta = () => {
    setIsEditingMeta(true);
  };

  const handleCancelEdit = () => {
    setIsEditingMeta(false);
    setEditingName(selectedFilter.name);
    setEditingDescription(selectedFilter.description || "");
  };

  const handleSaveMeta = async () => {
    if (!editingName.trim()) return;

    setIsSaving(true);
    try {
      const result = await updateFilterMutation.mutateAsync({
        id: selectedFilter.id,
        name: editingName.trim(),
        description: editingDescription.trim(),
      });

      if (result.success && result.filter) {
        setSelectedFilter(result.filter);
        setIsEditingMeta(false);
      }
    } catch (error) {
      console.error("Error updating filter:", error);
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveConfiguration = async () => {
    const filterData = {
      query,
      filters: selectedFilters,
      limit: resultLimit,
      scoreThreshold,
    };

    setIsSaving(true);
    try {
      const result = await updateFilterMutation.mutateAsync({
        id: selectedFilter.id,
        queryData: JSON.stringify(filterData),
      });

      if (result.success && result.filter) {
        setSelectedFilter(result.filter);
      }
    } catch (error) {
      console.error("Error updating filter configuration:", error);
    } finally {
      setIsSaving(false);
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const handleFilterChange = (
    facetType: keyof typeof selectedFilters,
    newValues: string[]
  ) => {
    setSelectedFilters((prev) => ({
      ...prev,
      [facetType]: newValues,
    }));
  };

  const handleDeleteFilter = async () => {
    const result = await deleteFilterMutation.mutateAsync({
      id: selectedFilter.id,
    });
    if (result.success) {
      setSelectedFilter(null);
      closePanelOnly();
    }
  };

  return (
    <div className="fixed right-0 top-14 bottom-0 w-80 bg-background border-l border-border/40 z-40 overflow-y-auto">
      <Card className="h-full rounded-none border-0 shadow-lg">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2">
              Knowledge Filter
            </CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={closePanelOnly}
              className="h-8 w-8 p-0"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-6">
          {/* Filter Name and Description */}
          <div className="space-y-4">
            {isEditingMeta ? (
              <div className="space-y-3">
                <div className="space-y-2">
                  <Label htmlFor="filter-name">Name</Label>
                  <Input
                    id="filter-name"
                    value={editingName}
                    onChange={(e) => setEditingName(e.target.value)}
                    placeholder="Filter name"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="filter-description">Description</Label>
                  <Textarea
                    id="filter-description"
                    value={editingDescription}
                    onChange={(e) => setEditingDescription(e.target.value)}
                    placeholder="Optional description"
                    rows={3}
                  />
                </div>
                <div className="flex gap-2">
                  <Button
                    onClick={handleSaveMeta}
                    disabled={!editingName.trim() || isSaving}
                    size="sm"
                    className="flex-1"
                  >
                    <Save className="h-3 w-3 mr-1" />
                    {isSaving ? "Saving..." : "Save"}
                  </Button>
                  <Button
                    onClick={handleCancelEdit}
                    variant="outline"
                    size="sm"
                    className="flex-1"
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <h3 className="font-semibold text-lg">
                      {selectedFilter.name}
                    </h3>
                    {selectedFilter.description && (
                      <p className="text-sm text-muted-foreground mt-1">
                        {selectedFilter.description}
                      </p>
                    )}
                  </div>
                  <Button
                    onClick={handleEditMeta}
                    variant="ghost"
                    size="sm"
                    className="h-8 w-8 p-0"
                  >
                    <Edit3 className="h-3 w-3" />
                  </Button>
                </div>
                <div className="text-xs text-muted-foreground">
                  Created {formatDate(selectedFilter.created_at)}
                  {selectedFilter.updated_at !== selectedFilter.created_at && (
                    <span>
                      {" "}
                      • Updated {formatDate(selectedFilter.updated_at)}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Search Query */}
          <div className="space-y-2">
            <Label htmlFor="search-query" className="text-sm font-medium">
              Search Query
            </Label>
            <Textarea
              id="search-query"
              placeholder="e.g., 'financial reports from Q4'"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="bg-background/50 border-border/50"
            />
          </div>

          {/* Filter Dropdowns */}
          <div className="space-y-4">
            <div className="space-y-2">
              <Label className="text-sm font-medium">Data Sources</Label>
              <MultiSelect
                options={(availableFacets.data_sources || []).map((bucket) => ({
                  value: bucket.key,
                  label: bucket.key,
                  count: bucket.count,
                }))}
                value={selectedFilters.data_sources}
                onValueChange={(values) =>
                  handleFilterChange("data_sources", values)
                }
                placeholder="Select data sources..."
                allOptionLabel="All Data Sources"
              />
            </div>

            <div className="space-y-2">
              <Label className="text-sm font-medium">Document Types</Label>
              <MultiSelect
                options={(availableFacets.document_types || []).map(
                  (bucket) => ({
                    value: bucket.key,
                    label: bucket.key,
                    count: bucket.count,
                  })
                )}
                value={selectedFilters.document_types}
                onValueChange={(values) =>
                  handleFilterChange("document_types", values)
                }
                placeholder="Select document types..."
                allOptionLabel="All Document Types"
              />
            </div>

            <div className="space-y-2">
              <Label className="text-sm font-medium">Owners</Label>
              <MultiSelect
                options={(availableFacets.owners || []).map((bucket) => ({
                  value: bucket.key,
                  label: bucket.key,
                  count: bucket.count,
                }))}
                value={selectedFilters.owners}
                onValueChange={(values) => handleFilterChange("owners", values)}
                placeholder="Select owners..."
                allOptionLabel="All Owners"
              />
            </div>

            <div className="space-y-2">
              <Label className="text-sm font-medium">Sources</Label>
              <MultiSelect
                options={(availableFacets.connector_types || []).map(
                  (bucket) => ({
                    value: bucket.key,
                    label: bucket.key,
                    count: bucket.count,
                  })
                )}
                value={selectedFilters.connector_types}
                onValueChange={(values) =>
                  handleFilterChange("connector_types", values)
                }
                placeholder="Select sources..."
                allOptionLabel="All Sources"
              />
            </div>

            {/* All/None buttons */}
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={selectAllFilters}
                className="h-auto px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 border-border/50"
              >
                All
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={clearAllFilters}
                className="h-auto px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 border-border/50"
              >
                None
              </Button>
            </div>

            {/* Result Limit Control - exactly like search page */}
            <div className="space-y-4 pt-4 border-t border-border/50">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-sm font-medium text-nowrap">Response limit</Label>
                  <Input
                    type="number"
                    min="1"
                    max="1000"
                    value={resultLimit}
                    onChange={(e) => {
                      const newLimit = Math.max(
                        1,
                        Math.min(1000, parseInt(e.target.value) || 1)
                      );
                      setResultLimit(newLimit);
                    }}
                    className="h-6 text-xs text-right px-2 bg-muted/30 !border-0 rounded ml-auto focus:ring-0 focus:outline-none"
                    style={{ width: "70px" }}
                  />
                </div>
                <Slider
                  value={[resultLimit]}
                  onValueChange={(values) => setResultLimit(values[0])}
                  max={1000}
                  min={1}
                  step={1}
                  className="w-full"
                />
              </div>

              {/* Score Threshold Control - exactly like search page */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-sm font-medium text-nowrap">Score threshold</Label>
                  <Input
                    type="number"
                    min="0"
                    max="5"
                    step="0.1"
                    value={scoreThreshold}
                    onChange={(e) =>
                      setScoreThreshold(parseFloat(e.target.value) || 0)
                    }
                    className="h-6 text-xs text-right px-2 bg-muted/30 !border-0 rounded ml-auto focus:ring-0 focus:outline-none"
                    style={{ width: "70px" }}
                  />
                </div>
                <Slider
                  value={[scoreThreshold]}
                  onValueChange={(values) => setScoreThreshold(values[0])}
                  max={5}
                  min={0}
                  step={0.1}
                  className="w-full"
                />
              </div>
            </div>

            {/* Save Configuration Button */}
            <div className="flex flex-col gap-3 pt-4 border-t border-border/50">
              <Button
                onClick={handleSaveConfiguration}
                disabled={isSaving}
                className="w-full"
                size="sm"
              >
                {isSaving ? (
                  <>
                    <RefreshCw className="h-3 w-3 mr-2 animate-spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <Save className="h-3 w-3 mr-2" />
                    Save Configuration
                  </>
                )}
              </Button>
              <Button
                variant="destructive"
                className="w-full"
                onClick={handleDeleteFilter}
              >
                Delete Filter
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
