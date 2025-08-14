"use client"

import { useState, useEffect } from 'react'
import { Filter, X, Edit3, Save, Settings, ChevronDown, ChevronUp, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { useKnowledgeFilter } from '@/contexts/knowledge-filter-context'

interface ParsedQueryData {
  query: string
  filters: {
    data_sources: string[]
    document_types: string[]
    owners: string[]
  }
  limit: number
  scoreThreshold: number
}

interface FacetBucket {
  key: string
  count: number
}

interface AvailableFacets {
  data_sources: FacetBucket[]
  document_types: FacetBucket[]
  owners: FacetBucket[]
}

export function KnowledgeFilterPanel() {
  const { selectedFilter, parsedFilterData, setSelectedFilter, isPanelOpen, closePanelOnly } = useKnowledgeFilter()
  
  // Edit mode states
  const [isEditingMeta, setIsEditingMeta] = useState(false)
  const [editingName, setEditingName] = useState('')
  const [editingDescription, setEditingDescription] = useState('')
  const [isSaving, setIsSaving] = useState(false)

  // Filter configuration states (mirror search page exactly)
  const [query, setQuery] = useState('')
  const [selectedFilters, setSelectedFilters] = useState({
    data_sources: ["*"] as string[], // Default to wildcard
    document_types: ["*"] as string[], // Default to wildcard
    owners: ["*"] as string[] // Default to wildcard
  })
  const [resultLimit, setResultLimit] = useState(10)
  const [scoreThreshold, setScoreThreshold] = useState(0)
  const [openSections, setOpenSections] = useState({
    data_sources: true,
    document_types: true,
    owners: true
  })
  
  // Available facets (loaded from API)
  const [availableFacets, setAvailableFacets] = useState<AvailableFacets>({
    data_sources: [],
    document_types: [],
    owners: []
  })

  // Load current filter data into controls
  useEffect(() => {
    if (selectedFilter && parsedFilterData) {
      setQuery(parsedFilterData.query || '')
      
      // Set the actual filter selections from the saved knowledge filter
      const filters = parsedFilterData.filters
      
      // If arrays are empty, default to wildcard (match everything)
      // Otherwise use the specific selections from the saved filter
      const processedFilters = {
        data_sources: filters.data_sources.length === 0 ? ["*"] : filters.data_sources,
        document_types: filters.document_types.length === 0 ? ["*"] : filters.document_types,
        owners: filters.owners.length === 0 ? ["*"] : filters.owners
      }
      
      console.log("[DEBUG] Loading filter selections:", processedFilters)
      
      setSelectedFilters(processedFilters)
      setResultLimit(parsedFilterData.limit || 10)
      setScoreThreshold(parsedFilterData.scoreThreshold || 0)
      setEditingName(selectedFilter.name)
      setEditingDescription(selectedFilter.description || '')
    }
  }, [selectedFilter, parsedFilterData])

  // Load available facets from API
  useEffect(() => {
    if (isPanelOpen) {
      loadAvailableFacets()
    }
  }, [isPanelOpen])

  const loadAvailableFacets = async () => {
    console.log("[DEBUG] Loading available facets...")
    try {
      // Do a search to get facets (similar to search page)
      const response = await fetch("/api/search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ 
          query: "*", // Use wildcard like search page to get all documents/facets
          limit: 1,
          scoreThreshold: 0
          // Omit filters entirely to get all available facets
        }),
      })

      const result = await response.json()
      console.log("[DEBUG] Search API response:", result)
      
      if (response.ok && result.aggregations) {
        const facets = {
          data_sources: result.aggregations.data_sources?.buckets || [],
          document_types: result.aggregations.document_types?.buckets || [],
          owners: result.aggregations.owners?.buckets || []
        }
        console.log("[DEBUG] Setting facets:", facets)
        setAvailableFacets(facets)
      } else {
        console.log("[DEBUG] No aggregations in response or response not ok")
      }
    } catch (error) {
      console.error("Failed to load available facets:", error)
    }
  }

  // Don't render if panel is closed or no filter selected
  if (!isPanelOpen || !selectedFilter || !parsedFilterData) return null

  const toggleSection = (section: keyof typeof openSections) => {
    setOpenSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }))
  }

  const handleFilterChange = (facetType: keyof typeof selectedFilters, value: string, checked: boolean) => {
    setSelectedFilters(prev => ({
      ...prev,
      [facetType]: checked 
        ? [...prev[facetType], value]
        : prev[facetType].filter(item => item !== value)
    }))
  }

  const selectAllFilters = () => {
    // Use wildcards instead of listing all specific items
    setSelectedFilters({
      data_sources: ["*"],
      document_types: ["*"],
      owners: ["*"]
    })
  }

  const clearAllFilters = () => {
    setSelectedFilters({
      data_sources: [],
      document_types: [],
      owners: []
    })
  }

  const handleEditMeta = () => {
    setIsEditingMeta(true)
  }

  const handleCancelEdit = () => {
    setIsEditingMeta(false)
    setEditingName(selectedFilter.name)
    setEditingDescription(selectedFilter.description || '')
  }

  const handleSaveMeta = async () => {
    if (!editingName.trim()) return

    setIsSaving(true)
    try {
      const response = await fetch(`/api/knowledge-filter/${selectedFilter.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: editingName.trim(),
          description: editingDescription.trim(),
        }),
      })

      const result = await response.json()
      if (response.ok && result.success) {
        const updatedFilter = {
          ...selectedFilter,
          name: editingName.trim(),
          description: editingDescription.trim(),
          updated_at: new Date().toISOString(),
        }
        setSelectedFilter(updatedFilter)
        setIsEditingMeta(false)
      }
    } catch (error) {
      console.error('Error updating filter:', error)
    } finally {
      setIsSaving(false)
    }
  }

  const handleSaveConfiguration = async () => {
    const filterData = {
      query,
      filters: selectedFilters,
      limit: resultLimit,
      scoreThreshold
    }

    setIsSaving(true)
    try {
      const response = await fetch(`/api/knowledge-filter/${selectedFilter.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          queryData: JSON.stringify(filterData)
        }),
      })

      const result = await response.json()
      if (response.ok && result.success) {
        // Update the filter in context
        const updatedFilter = {
          ...selectedFilter,
          query_data: JSON.stringify(filterData),
          updated_at: new Date().toISOString(),
        }
        setSelectedFilter(updatedFilter)
      }
    } catch (error) {
      console.error('Error updating filter configuration:', error)
    } finally {
      setIsSaving(false)
    }
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  const FacetSection = ({ 
    title, 
    buckets, 
    facetType,
    isOpen,
    onToggle 
  }: { 
    title: string
    buckets: FacetBucket[]
    facetType: keyof typeof selectedFilters
    isOpen: boolean
    onToggle: () => void
  }) => {
    if (!buckets || buckets.length === 0) return null
    
    const isAllSelected = selectedFilters[facetType].includes("*") // Wildcard
    const hasSpecificSelections = selectedFilters[facetType].some(item => item !== "*")
    
    const handleAllToggle = (checked: boolean) => {
      if (checked) {
        // Select "All" - clear specific selections and add wildcard
        setSelectedFilters(prev => ({
          ...prev,
          [facetType]: ["*"]
        }))
      } else {
        // Unselect "All" - remove wildcard but keep any specific selections
        setSelectedFilters(prev => ({
          ...prev,
          [facetType]: prev[facetType].filter(item => item !== "*")
        }))
      }
    }
    
    const handleSpecificToggle = (value: string, checked: boolean) => {
      setSelectedFilters(prev => {
        let newValues = [...prev[facetType]]
        
        // Remove wildcard if selecting specific items
        newValues = newValues.filter(item => item !== "*")
        
        if (checked) {
          newValues.push(value)
        } else {
          newValues = newValues.filter(item => item !== value)
        }
        
        return {
          ...prev,
          [facetType]: newValues
        }
      })
    }
    
    return (
      <Collapsible open={isOpen} onOpenChange={onToggle}>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" className="w-full justify-between p-0 h-auto font-medium text-left">
            <span className="text-sm font-medium">{title}</span>
            {isOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="space-y-2 mt-3">
          {/* "All" wildcard option */}
          <div className="flex items-center space-x-2 pb-2 border-b border-border/30">
            <Checkbox
              id={`${facetType}-all`}
              checked={isAllSelected}
              onCheckedChange={handleAllToggle}
            />
            <Label 
              htmlFor={`${facetType}-all`}
              className="text-sm font-medium flex-1 cursor-pointer flex items-center justify-between"
            >
              <span>All {title}</span>
              <span className="text-xs text-blue-500 bg-blue-500/10 px-1.5 py-0.5 rounded ml-2 flex-shrink-0">
                *
              </span>
            </Label>
          </div>
          
          {/* Individual items - disabled if "All" is selected */}
          {buckets.map((bucket, index) => {
            const isSelected = selectedFilters[facetType].includes(bucket.key)
            const isDisabled = isAllSelected
            
            return (
              <div key={index} className={`flex items-center space-x-2 ${isDisabled ? 'opacity-50' : ''}`}>
                <Checkbox
                  id={`${facetType}-${index}`}
                  checked={isSelected}
                  disabled={isDisabled}
                  onCheckedChange={(checked) => 
                    handleSpecificToggle(bucket.key, checked as boolean)
                  }
                />
                <Label 
                  htmlFor={`${facetType}-${index}`}
                  className={`text-sm font-normal flex-1 flex items-center justify-between ${isDisabled ? 'cursor-not-allowed' : 'cursor-pointer'}`}
                >
                  <span className="truncate" title={bucket.key}>
                    {bucket.key}
                  </span>
                  <span className="text-xs text-muted-foreground bg-muted/50 px-1.5 py-0.5 rounded ml-2 flex-shrink-0">
                    {bucket.count}
                  </span>
                </Label>
              </div>
            )
          })}
        </CollapsibleContent>
      </Collapsible>
    )
  }

  return (
    <div className="fixed right-0 top-14 bottom-0 w-80 bg-background border-l border-border/40 z-40 overflow-y-auto">
      <Card className="h-full rounded-none border-0 shadow-lg">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2">
              <Settings className="h-5 w-5" />
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
          <CardDescription>
            Configure your knowledge filter settings
          </CardDescription>
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
                    {isSaving ? 'Saving...' : 'Save'}
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
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <h3 className="font-semibold text-lg">{selectedFilter.name}</h3>
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
                    <span> • Updated {formatDate(selectedFilter.updated_at)}</span>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Search Query */}
          <div className="space-y-2">
            <Label htmlFor="search-query" className="text-sm font-medium">Search Query</Label>
            <Input
              id="search-query"
              type="text"
              placeholder="e.g., 'financial reports from Q4'"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="bg-background/50 border-border/50"
            />
          </div>

          {/* Facet Sections - exactly like search page */}
          <div className="space-y-6">
            <FacetSection
              title="Data Sources"
              buckets={availableFacets.data_sources || []}
              facetType="data_sources"
              isOpen={openSections.data_sources}
              onToggle={() => toggleSection('data_sources')}
            />
            <FacetSection
              title="Document Types"
              buckets={availableFacets.document_types || []}
              facetType="document_types"
              isOpen={openSections.document_types}
              onToggle={() => toggleSection('document_types')}
            />
            <FacetSection
              title="Owners"
              buckets={availableFacets.owners || []}
              facetType="owners"
              isOpen={openSections.owners}
              onToggle={() => toggleSection('owners')}
            />

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
                  <Label className="text-sm font-medium">Limit</Label>
                  <Input
                    type="number"
                    min="1"
                    max="1000"
                    value={resultLimit}
                    onChange={(e) => {
                      const newLimit = Math.max(1, Math.min(1000, parseInt(e.target.value) || 1))
                      setResultLimit(newLimit)
                    }}
                    className="w-16 h-6 text-xs text-center"
                  />
                </div>
                <input
                  type="range"
                  min={1}
                  max={1000}
                  value={resultLimit}
                  onChange={(e) => setResultLimit(parseInt(e.target.value))}
                  className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                />
              </div>

              {/* Score Threshold Control - exactly like search page */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-sm font-medium">Score Threshold</Label>
                  <Input
                    type="number"
                    min="0"
                    max="1"
                    step="0.01"
                    value={scoreThreshold}
                    onChange={(e) => setScoreThreshold(parseFloat(e.target.value) || 0)}
                    className="w-16 h-6 text-xs text-center"
                  />
                </div>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  value={scoreThreshold}
                  onChange={(e) => setScoreThreshold(parseFloat(e.target.value))}
                  className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                />
              </div>
            </div>

            {/* Save Configuration Button */}
            <div className="pt-4 border-t border-border/50">
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
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}