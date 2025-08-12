"use client"

import { useState, useEffect, useCallback } from "react"
import { useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Checkbox } from "@/components/ui/checkbox"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Search, Loader2, FileText, Zap, ChevronDown, ChevronUp, X, Settings, Save } from "lucide-react"
import { ProtectedRoute } from "@/components/protected-route"
import { toast } from 'sonner'

interface SearchResult {
  filename: string
  mimetype: string
  page: number
  text: string
  score: number
  source_url?: string
  owner?: string
}

interface FacetBucket {
  key: string
  count: number
}

interface Facets {
  data_sources?: FacetBucket[]
  document_types?: FacetBucket[]
  owners?: FacetBucket[]
}

interface AggregationBucket {
  key: string
  doc_count: number
}

interface Aggregations {
  data_sources?: {
    buckets: AggregationBucket[]
  }
  document_types?: {
    buckets: AggregationBucket[]
  }
  owners?: {
    buckets: AggregationBucket[]
  }
}

interface SearchResponse {
  results: SearchResult[]
  aggregations: Aggregations
  error?: string
}

interface SelectedFilters {
  data_sources: string[]
  document_types: string[]
  owners: string[]
}

function SearchPage() {
  const searchParams = useSearchParams()
  const [query, setQuery] = useState("")
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<SearchResult[]>([])
  const [facets, setFacets] = useState<Facets>({})
  const [searchPerformed, setSearchPerformed] = useState(false)
  const [selectedFilters, setSelectedFilters] = useState<SelectedFilters>({
    data_sources: [],
    document_types: [],
    owners: []
  })
  const [openSections, setOpenSections] = useState({
    data_sources: true,
    document_types: true,
    owners: true
  })
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [resultLimit, setResultLimit] = useState(10)
  const [scoreThreshold, setScoreThreshold] = useState(0)
  const [showSaveModal, setShowSaveModal] = useState(false)
  const [contextTitle, setContextTitle] = useState("")
  const [contextDescription, setContextDescription] = useState("")
  const [savingContext, setSavingContext] = useState(false)
  const [loadedContextName, setLoadedContextName] = useState<string | null>(null)

  const loadContext = useCallback(async (contextId: string) => {
    try {
      const response = await fetch(`/api/contexts/${contextId}`, {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
      })

      const result = await response.json()
      if (response.ok && result.success) {
        const context = result.context
        const parsedQueryData = JSON.parse(context.query_data)
        
        // Load the context data into state
        setQuery(parsedQueryData.query)
        setSelectedFilters(parsedQueryData.filters)
        setResultLimit(parsedQueryData.limit)
        setScoreThreshold(parsedQueryData.scoreThreshold)
        setLoadedContextName(context.name)
        
        // Automatically perform the search
        setTimeout(() => {
          handleSearch()
        }, 100)
      } else {
        console.error("Failed to load context:", result.error)
      }
    } catch (err) {
      console.error("Error loading context:", err)
    }
  }, [])

  // Load context if contextId is provided in URL
  useEffect(() => {
    const contextId = searchParams.get('contextId')
    if (contextId) {
      loadContext(contextId)
    }
  }, [searchParams, loadContext])

  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!query.trim()) return

    setLoading(true)
    setSearchPerformed(false)

    try {
      const response = await fetch("/api/search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ 
          query,
          limit: resultLimit,
          scoreThreshold,
          ...(searchPerformed && { filters: selectedFilters })
        }),
      })

      const result: SearchResponse = await response.json()
      
      if (response.ok) {
        setResults(result.results || [])
        
        // Process aggregations into facets
        const aggs = result.aggregations
        const processedFacets: Facets = {}
        const newSelectedFilters: SelectedFilters = {
          data_sources: [],
          document_types: [],
          owners: []
        }
        
        if (aggs && Object.keys(aggs).length > 0) {
          processedFacets.data_sources = aggs.data_sources?.buckets?.map((b: AggregationBucket) => ({ key: b.key, count: b.doc_count })).filter((b: FacetBucket) => b.count > 0) || []
          processedFacets.document_types = aggs.document_types?.buckets?.map((b: AggregationBucket) => ({ key: b.key, count: b.doc_count })).filter((b: FacetBucket) => b.count > 0) || []
          processedFacets.owners = aggs.owners?.buckets?.map((b: AggregationBucket) => ({ key: b.key, count: b.doc_count })).filter((b: FacetBucket) => b.count > 0) || []
          
          // Set all filters as checked by default
          newSelectedFilters.data_sources = processedFacets.data_sources?.map(f => f.key) || []
          newSelectedFilters.document_types = processedFacets.document_types?.map(f => f.key) || []
          newSelectedFilters.owners = processedFacets.owners?.map(f => f.key) || []
        }
        
        setFacets(processedFacets)
        setSelectedFilters(newSelectedFilters)
        setSearchPerformed(true)
      } else {
        console.error("Search failed:", result.error)
        setResults([])
        setFacets({})
        setSelectedFilters({
          data_sources: [],
          document_types: [],
          owners: []
        })
        setSearchPerformed(true)
      }
    } catch (error) {
      console.error("Search error:", error)
      setResults([])
      setFacets({})
      setSelectedFilters({
        data_sources: [],
        document_types: [],
        owners: []
      })
      setSearchPerformed(true)
    } finally {
      setLoading(false)
    }
  }

  const handleFilterChange = async (facetType: keyof SelectedFilters, value: string, checked: boolean) => {
    const newFilters = {
      ...selectedFilters,
      [facetType]: checked 
        ? [...selectedFilters[facetType], value]
        : selectedFilters[facetType].filter(item => item !== value)
    }
    
    setSelectedFilters(newFilters)
    
    // Re-search immediately if search has been performed
    if (searchPerformed && query.trim()) {
      setLoading(true)
      try {
        const response = await fetch("/api/search", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ 
            query,
            limit: resultLimit,
            scoreThreshold,
            filters: newFilters
          }),
        })

        const result: SearchResponse = await response.json()
        
        if (response.ok) {
          setResults(result.results || [])
        } else {
          console.error("Search failed:", result.error)
          setResults([])
        }
      } catch (error) {
        console.error("Search error:", error)
        setResults([])
      } finally {
        setLoading(false)
      }
    }
  }

  const clearAllFilters = () => {
    setSelectedFilters({
      data_sources: [],
      document_types: [],
      owners: []
    })
  }

  const selectAllFilters = () => {
    setSelectedFilters({
      data_sources: facets.data_sources?.map(f => f.key) || [],
      document_types: facets.document_types?.map(f => f.key) || [],
      owners: facets.owners?.map(f => f.key) || []
    })
  }

  const toggleSection = (section: keyof typeof openSections) => {
    setOpenSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }))
  }

  const getSelectedFilterCount = () => {
    return selectedFilters.data_sources.length + 
           selectedFilters.document_types.length + 
           selectedFilters.owners.length
  }

  const handleSaveContext = async () => {
    const contextId = searchParams.get('contextId')
    
    // If no contextId present and no title, we need the modal
    if (!contextId && !contextTitle.trim()) return

    setSavingContext(true)
    
    try {
      const contextData = {
        query,
        filters: selectedFilters,
        limit: resultLimit,
        scoreThreshold
      }

      let response;
      
      if (contextId) {
        // Update existing context (upsert)
        response = await fetch(`/api/contexts/${contextId}`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            queryData: JSON.stringify(contextData)
          }),
        })
      } else {
        // Create new context
        response = await fetch("/api/contexts", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            name: contextTitle,
            description: contextDescription,
            queryData: JSON.stringify(contextData)
          }),
        })
      }

      const result = await response.json()
      
      if (response.ok && result.success) {
        if (!contextId) {
          // Reset modal state only if we were creating a new context
          setShowSaveModal(false)
          setContextTitle("")
          setContextDescription("")
        }
        toast.success(contextId ? "Context updated successfully" : "Context saved successfully")
      } else {
        toast.error(contextId ? "Failed to update context" : "Failed to save context")
      }
    } catch {
      toast.error(contextId ? "Error updating context" : "Error saving context")
    } finally {
      setSavingContext(false)
    }
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
    facetType: keyof SelectedFilters
    isOpen: boolean
    onToggle: () => void
  }) => {
    if (!buckets || buckets.length === 0) return null
    
    return (
      <Collapsible open={isOpen} onOpenChange={onToggle}>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" className="w-full justify-between p-0 h-auto font-medium text-left">
            <span className="text-sm font-medium">{title}</span>
            {isOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="space-y-2 mt-3">
          {buckets.map((bucket, index) => {
            const isSelected = selectedFilters[facetType].includes(bucket.key)
            return (
              <div key={index} className="flex items-center space-x-2">
                <Checkbox
                  id={`${facetType}-${index}`}
                  checked={isSelected}
                  onCheckedChange={(checked) => 
                    handleFilterChange(facetType, bucket.key, checked as boolean)
                  }
                />
                <Label 
                  htmlFor={`${facetType}-${index}`}
                  className="text-sm font-normal flex-1 cursor-pointer flex items-center justify-between"
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
    <div className="space-y-8">
      {/* Hero Section */}
      <div className="space-y-4">
        <div className="mb-4">
          <h1 className="text-4xl font-bold tracking-tight text-white">
            Search
          </h1>
        </div>
        <p className="text-xl text-muted-foreground">
          Find documents using hybrid search
        </p>
        <p className="text-sm text-muted-foreground max-w-2xl">
          Enter your search query to find relevant documents using AI-powered semantic search combined with keyword matching across your document collection.
        </p>
      </div>

      {/* Search Interface */}
      <Card className="w-full bg-card/50 backdrop-blur-sm border-border/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-5 w-5" />
            Search Documents
            {loadedContextName && (
              <span className="text-sm font-normal text-blue-400 bg-blue-400/10 px-2 py-1 rounded">
                Context: {loadedContextName}
              </span>
            )}
          </CardTitle>
          <CardDescription>
            Enter your search query to find relevant documents using hybrid search (semantic + keyword)
            {loadedContextName && (
              <span className="block text-blue-400 text-xs mt-1">
                Search configuration loaded from saved context
              </span>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <form onSubmit={handleSearch} className="space-y-4">
            <div className="space-y-3">
              <Label htmlFor="search-query" className="font-medium">
                Search Query
              </Label>
              <div className="flex gap-2">
                <Input
                  id="search-query"
                  type="text"
                  placeholder="e.g., 'financial reports from Q4' or 'user authentication setup'"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="h-12 bg-background/50 border-border/50 focus:border-blue-400/50 focus:ring-blue-400/20 flex-1"
                />
                <Button
                  type="submit"
                  disabled={!query.trim() || loading}
                  className="h-12 px-6 transition-all duration-200"
                >
                  {loading ? (
                    <>
                      <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                      Searching...
                    </>
                  ) : (
                    <>
                      <Search className="mr-2 h-5 w-5" />
                      Search
                    </>
                  )}
                </Button>
              </div>
            </div>
          </form>

          {/* Search Results with Filters */}
          {searchPerformed && (
            <div className="space-y-4">
              {/* Search Results Header - Always visible when search is performed */}
              <div className="flex justify-between items-center">
                <h2 className="text-2xl font-semibold flex items-center gap-2">
                  <Zap className="h-6 w-6 text-yellow-400" />
                  Search Results
                </h2>
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-2 bg-green-400 rounded-full animate-pulse"></div>
                    <span className="text-sm text-muted-foreground">
                      {results.length} result{results.length !== 1 ? 's' : ''} returned
                    </span>
                  </div>
                  {/* Filter Toggle - Only visible when filters are available */}
                  {((facets.data_sources?.length ?? 0) > 0 || (facets.document_types?.length ?? 0) > 0 || (facets.owners?.length ?? 0) > 0) && (
                    <Button
                      variant="outline"
                      onClick={() => setSidebarOpen(!sidebarOpen)}
                      className="flex items-center gap-2"
                    >
                      <Settings className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </div>

              <div className="flex gap-6">
                {/* Main Content */}
                <div className="flex-1 space-y-6">
                  {/* Active Filters Display */}
                  {getSelectedFilterCount() > 0 && getSelectedFilterCount() < (facets.data_sources?.length || 0) + (facets.document_types?.length || 0) + (facets.owners?.length || 0) && (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-medium">Active Filters</h3>
                        <div className="flex gap-1">
                          <Button variant="ghost" size="sm" onClick={selectAllFilters} className="h-auto px-2 py-1 text-xs">
                            Select all
                          </Button>
                          <Button variant="ghost" size="sm" onClick={clearAllFilters} className="h-auto px-2 py-1 text-xs">
                            Clear all
                          </Button>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(selectedFilters).map(([facetType, values]) =>
                          values.map((value: string) => (
                            <div key={`${facetType}-${value}`} className="flex items-center gap-1 bg-primary/10 text-primary px-2 py-1 rounded-md text-xs">
                              <span>{value}</span>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-auto w-auto p-0.5 hover:bg-primary/20"
                                onClick={() => handleFilterChange(facetType as keyof SelectedFilters, value, false)}
                              >
                                <X className="h-3 w-3" />
                              </Button>
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  )}

                  {/* Results Section */}
                  <div>
                    {results.length === 0 ? (
                      <Card className="bg-muted/20 border-dashed border-muted-foreground/30">
                        <CardContent className="pt-8 pb-8">
                          <div className="text-center space-y-3">
                            <div className="mx-auto w-16 h-16 bg-muted/30 rounded-full flex items-center justify-center">
                              <Search className="h-8 w-8 text-muted-foreground/50" />
                            </div>
                            <p className="text-lg font-medium text-muted-foreground">
                              No documents found
                            </p>
                            <p className="text-sm text-muted-foreground/70 max-w-md mx-auto">
                              Try adjusting your search terms or check if documents have been indexed.
                            </p>
                          </div>
                        </CardContent>
                      </Card>
                    ) : (
                      <div className="space-y-4">
                        {results.map((result, index) => (
                          <Card key={index} className="bg-card/50 backdrop-blur-sm border-border/50 hover:bg-card/70 transition-all duration-200 hover:shadow-lg hover:shadow-blue-500/10">
                            <CardHeader className="pb-3">
                              <div className="flex items-center justify-between">
                                <CardTitle className="text-lg flex items-center gap-3">
                                  <div className="p-2 rounded-lg bg-blue-500/20 border border-blue-500/30">
                                    <FileText className="h-4 w-4 text-blue-400" />
                                  </div>
                                  <span className="truncate">{result.filename}</span>
                                </CardTitle>
                                <div className="flex items-center gap-2">
                                  <div className="px-2 py-1 rounded-md bg-green-500/20 border border-green-500/30">
                                    <span className="text-xs font-medium text-green-400">
                                      {result.score.toFixed(2)}
                                    </span>
                                  </div>
                                </div>
                              </div>
                              <CardDescription className="flex items-center gap-4 text-sm">
                                <span className="px-2 py-1 rounded bg-muted/50 text-muted-foreground">
                                  {result.mimetype}
                                </span>
                                <span className="text-muted-foreground">
                                  Page {result.page}
                                </span>
                              </CardDescription>
                            </CardHeader>
                            <CardContent>
                              <div className="border-l-2 border-blue-400/50 pl-4 py-2 bg-muted/20 rounded-r-lg">
                                <p className="text-sm leading-relaxed text-foreground/90">
                                  {result.text}
                                </p>
                              </div>
                            </CardContent>
                          </Card>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* Right Sidebar - Settings */}
                {((facets.data_sources?.length ?? 0) > 0 || (facets.document_types?.length ?? 0) > 0 || (facets.owners?.length ?? 0) > 0) && sidebarOpen && (
                  <div className="w-64 space-y-6 flex-shrink-0">
                    <div className="flex items-center justify-between">
                      <h2 className="text-lg font-semibold flex items-center gap-2">
                        <Settings className="h-5 w-5" />
                        Search Configuration
                      </h2>
                    </div>

                    <div className="space-y-6">
                      <FacetSection
                        title="Data Sources"
                        buckets={facets.data_sources || []}
                        facetType="data_sources"
                        isOpen={openSections.data_sources}
                        onToggle={() => toggleSection('data_sources')}
                      />
                      <FacetSection
                        title="Document Types"
                        buckets={facets.document_types || []}
                        facetType="document_types"
                        isOpen={openSections.document_types}
                        onToggle={() => toggleSection('document_types')}
                      />
                      <FacetSection
                        title="Owners"
                        buckets={facets.owners || []}
                        facetType="owners"
                        isOpen={openSections.owners}
                        onToggle={() => toggleSection('owners')}
                      />

                      {/* All/None buttons - moved below facets */}
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

                      {/* Result Limit Control */}
                      <div className="space-y-4 pt-4 border-t border-border/50">
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <Label className="text-sm font-medium">Limit</Label>
                            <Input
                              type="number"
                              min="1"
                              max="1000"
                              value={resultLimit}
                              onChange={async (e) => {
                                const newLimit = Math.max(1, Math.min(1000, parseInt(e.target.value) || 1))
                                setResultLimit(newLimit)
                                
                                // Re-search if search has been performed
                                if (searchPerformed && query.trim()) {
                                  setLoading(true)
                                  try {
                                    const response = await fetch("/api/search", {
                                      method: "POST",
                                      headers: {
                                        "Content-Type": "application/json",
                                      },
                                      body: JSON.stringify({ 
                                        query,
                                        limit: newLimit,
                                        scoreThreshold,
                                        filters: selectedFilters
                                      }),
                                    })

                                    const result: SearchResponse = await response.json()
                                    
                                    if (response.ok) {
                                      setResults(result.results || [])
                                    } else {
                                      console.error("Search failed:", result.error)
                                      setResults([])
                                    }
                                  } catch (error) {
                                    console.error("Search error:", error)
                                    setResults([])
                                  } finally {
                                    setLoading(false)
                                  }
                                }
                              }}
                              className="w-16 h-6 text-xs text-center"
                            />
                          </div>
                          <input
                            type="range"
                            min={1}
                            max={1000}
                            value={resultLimit}
                            onChange={async (e) => {
                              const value = parseInt(e.target.value)
                              setResultLimit(value)
                              
                              // Re-search if search has been performed
                              if (searchPerformed && query.trim()) {
                                setLoading(true)
                                try {
                                  const response = await fetch("/api/search", {
                                    method: "POST",
                                    headers: {
                                      "Content-Type": "application/json",
                                    },
                                    body: JSON.stringify({ 
                                      query,
                                      limit: value,
                                      scoreThreshold,
                                      filters: selectedFilters
                                    }),
                                  })

                                  const result: SearchResponse = await response.json()
                                  
                                  if (response.ok) {
                                    setResults(result.results || [])
                                  } else {
                                    console.error("Search failed:", result.error)
                                    setResults([])
                                  }
                                } catch (error) {
                                  console.error("Search error:", error)
                                  setResults([])
                                } finally {
                                  setLoading(false)
                                }
                              }
                            }}
                            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                          />
                        </div>

                        {/* Score Threshold Control */}
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <Label className="text-sm font-medium">Score Threshold</Label>
                            <Input
                              type="number"
                              min="0"
                              max="10"
                              step="0.1"
                              value={scoreThreshold}
                              onChange={async (e) => {
                                const newThreshold = Math.max(0, Math.min(10, parseFloat(e.target.value) || 0))
                                setScoreThreshold(newThreshold)
                                
                                // Re-search if search has been performed
                                if (searchPerformed && query.trim()) {
                                  setLoading(true)
                                  try {
                                    const response = await fetch("/api/search", {
                                      method: "POST",
                                      headers: {
                                        "Content-Type": "application/json",
                                      },
                                      body: JSON.stringify({ 
                                        query,
                                        limit: resultLimit,
                                        scoreThreshold: newThreshold,
                                        filters: selectedFilters
                                      }),
                                    })

                                    const result: SearchResponse = await response.json()
                                    
                                    if (response.ok) {
                                      setResults(result.results || [])
                                    } else {
                                      console.error("Search failed:", result.error)
                                      setResults([])
                                    }
                                  } catch (error) {
                                    console.error("Search error:", error)
                                    setResults([])
                                  } finally {
                                    setLoading(false)
                                  }
                                }
                              }}
                              className="w-16 h-6 text-xs text-center"
                            />
                          </div>
                          <input
                            type="range"
                            min={0}
                            max={10}
                            step={0.1}
                            value={scoreThreshold}
                            onChange={async (e) => {
                              const value = parseFloat(e.target.value)
                              setScoreThreshold(value)
                              
                              // Re-search if search has been performed
                              if (searchPerformed && query.trim()) {
                                setLoading(true)
                                try {
                                  const response = await fetch("/api/search", {
                                    method: "POST",
                                    headers: {
                                      "Content-Type": "application/json",
                                    },
                                    body: JSON.stringify({ 
                                      query,
                                      limit: resultLimit,
                                      scoreThreshold: value,
                                      filters: selectedFilters
                                    }),
                                  })

                                  const result: SearchResponse = await response.json()
                                  
                                  if (response.ok) {
                                    setResults(result.results || [])
                                  } else {
                                    console.error("Search failed:", result.error)
                                    setResults([])
                                  }
                                } catch (error) {
                                  console.error("Search error:", error)
                                  setResults([])
                                } finally {
                                  setLoading(false)
                                }
                              }
                            }}
                            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                          />
                        </div>
                      </div>

                      {/* Save Context Button */}
                      <div className="pt-4 border-t border-border/50">
                        <Button
                          onClick={() => {
                            const contextId = searchParams.get('contextId')
                            if (contextId) {
                              handleSaveContext()
                            } else {
                              setShowSaveModal(true)
                            }
                          }}
                          disabled={!searchPerformed || !query.trim() || savingContext}
                          className="w-full flex items-center gap-2"
                          variant="outline"
                        >
                          {savingContext ? (
                            <>
                              <Loader2 className="h-4 w-4 animate-spin" />
                              {searchParams.get('contextId') ? 'Updating...' : 'Saving...'}
                            </>
                          ) : (
                            <>
                              <Save className="h-4 w-4" />
                              {searchParams.get('contextId') ? 'Update Context' : 'Save Context'}
                            </>
                          )}
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Empty State */}
          {!searchPerformed && (
            <div className="h-32 flex items-center justify-center">
              <p className="text-muted-foreground/50 text-sm">
                Enter a search query above to get started
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Save Context Modal */}
      {showSaveModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card border border-border rounded-lg p-6 w-full max-w-md mx-4">
            <h3 className="text-lg font-semibold mb-4">Save Search Context</h3>
            
            <div className="space-y-4">
              <div>
                <Label htmlFor="context-title" className="font-medium">
                  Title <span className="text-red-400">*</span>
                </Label>
                <Input
                  id="context-title"
                  type="text"
                  placeholder="Enter a title for this search context"
                  value={contextTitle}
                  onChange={(e) => setContextTitle(e.target.value)}
                  className="mt-1"
                />
              </div>
              
              <div>
                <Label htmlFor="context-description" className="font-medium">
                  Description (optional)
                </Label>
                <Input
                  id="context-description"
                  type="text"
                  placeholder="Brief description of this search context"
                  value={contextDescription}
                  onChange={(e) => setContextDescription(e.target.value)}
                  className="mt-1"
                />
              </div>
            </div>
            
            <div className="flex justify-end gap-2 mt-6">
              <Button
                variant="outline"
                onClick={() => {
                  setShowSaveModal(false)
                  setContextTitle("")
                  setContextDescription("")
                }}
                disabled={savingContext}
              >
                Cancel
              </Button>
              <Button
                onClick={handleSaveContext}
                disabled={!contextTitle.trim() || savingContext}
                className="flex items-center gap-2"
              >
                {savingContext ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <Save className="h-4 w-4" />
                    Save Context
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function ProtectedSearchPage() {
  return (
    <ProtectedRoute>
      <SearchPage />
    </ProtectedRoute>
  )
}
