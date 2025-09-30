"use client";

import { useState, useEffect } from "react";
import { X, Save, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { MultiSelect } from "@/components/ui/multi-select";
import { Slider } from "@/components/ui/slider";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useDeleteFilter } from "@/app/api/mutations/useDeleteFilter";
import { useUpdateFilter } from "@/app/api/mutations/useUpdateFilter";
import { useCreateFilter } from "@/app/api/mutations/useCreateFilter";
import { useGetSearchAggregations } from "@/src/app/api/queries/useGetSearchAggregations";
import { FilterIconPopover, IconKey } from "@/components/filter-icon-popover";

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

export const filterAccentClasses: Record<
  "zinc" | "pink" | "purple" | "indigo" | "emerald" | "amber" | "red" | "",
  string
> = {
  zinc: "bg-accent text-muted-foreground",
  pink: "bg-accent-pink text-accent-pink-foreground",
  purple: "bg-accent-purple text-accent-purple-foreground",
  indigo: "bg-accent-indigo text-accent-indigo-foreground",
  emerald: "bg-accent-emerald text-accent-emerald-foreground",
  amber: "bg-accent-amber text-accent-amber-foreground",
  red: "bg-accent-red text-accent-red-foreground",
  "": "bg-accent text-muted-foreground",
};

export function KnowledgeFilterPanel() {
  const {
    selectedFilter,
    parsedFilterData,
    setSelectedFilter,
    isPanelOpen,
    closePanelOnly,
    createMode,
    endCreateMode,
  } = useKnowledgeFilter();
  const deleteFilterMutation = useDeleteFilter();
  const updateFilterMutation = useUpdateFilter();
  const createFilterMutation = useCreateFilter();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [color, setColor] = useState<
    "zinc" | "pink" | "purple" | "indigo" | "emerald" | "amber" | "red"
  >("zinc");
  const [iconKey, setIconKey] = useState<IconKey>();

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

  // Load current filter data into controls when a filter is selected
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
      setName(selectedFilter.name);
      setDescription(selectedFilter.description || "");
      setColor(parsedFilterData.color || "zinc");
      setIconKey(parsedFilterData.icon as IconKey);
    }
  }, [selectedFilter, parsedFilterData]);

  // Initialize defaults when entering create mode
  useEffect(() => {
    if (createMode && parsedFilterData) {
      setQuery(parsedFilterData.query || "");
      setSelectedFilters(parsedFilterData.filters);
      setResultLimit(parsedFilterData.limit || 10);
      setScoreThreshold(parsedFilterData.scoreThreshold || 0);
      setName("");
      setDescription("");
      setColor(parsedFilterData.color || "zinc");
      setIconKey(parsedFilterData.icon as IconKey);
    }
  }, [createMode, parsedFilterData]);

  // Load available facets using search aggregations hook
  const { data: aggregations } = useGetSearchAggregations("*", 1, 0, {
    enabled: isPanelOpen,
    placeholderData: (prev) => prev,
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

  // Don't render if panel is closed or we don't have any data
  if (!isPanelOpen || !parsedFilterData) return null;

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

  const handleSaveConfiguration = async () => {
    if (!name.trim()) return;
    const filterData = {
      query,
      filters: selectedFilters,
      limit: resultLimit,
      scoreThreshold,
      color,
      icon: iconKey,
    };

    setIsSaving(true);
    try {
      if (createMode) {
        const result = await createFilterMutation.mutateAsync({
          name: name.trim(),
          description: description.trim(),
          queryData: JSON.stringify(filterData),
        });
        if (result.success && result.filter) {
          setSelectedFilter(result.filter);
          endCreateMode();
        }
      } else if (selectedFilter) {
        const result = await updateFilterMutation.mutateAsync({
          id: selectedFilter.id,
          name: name.trim(),
          description: description.trim(),
          queryData: JSON.stringify(filterData),
        });
        if (result.success && result.filter) {
          setSelectedFilter(result.filter);
        }
      }
    } catch (error) {
      console.error("Error saving knowledge filter:", error);
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
    if (!selectedFilter) return;
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
          <div className="space-y-3">
            <div className="space-y-2">
              <Label htmlFor="filter-name">Filter name</Label>
              <div className="flex items-center gap-2">
                <FilterIconPopover
                  color={color}
                  iconKey={iconKey}
                  onColorChange={setColor}
                  onIconChange={(k) => setIconKey(k)}
                />
                <Input
                  id="filter-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Filter name"
                />
              </div>
            </div>
            {!createMode && selectedFilter?.created_at && (
              <div className="space-y-2 text-xs text-right text-muted-foreground">
                <span className="text-placeholder-foreground">Created</span>{" "}
                {formatDate(selectedFilter.created_at)}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="filter-description">Description</Label>
              <Textarea
                id="filter-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional description"
                rows={3}
              />
            </div>
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
              rows={3}
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
                  <Label className="text-sm font-medium text-nowrap">
                    Response limit
                  </Label>
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
                  <Label className="text-sm font-medium text-nowrap">
                    Score threshold
                  </Label>
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
              {!createMode && (
                <Button
                  variant="destructive"
                  className="w-full"
                  onClick={handleDeleteFilter}
                >
                  Delete Filter
                </Button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
