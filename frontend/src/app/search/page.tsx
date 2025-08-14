"use client"

import { useState, useEffect, useCallback, useRef } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Search, Loader2, FileText, Zap } from "lucide-react"
import { ProtectedRoute } from "@/components/protected-route"
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context"

interface SearchResult {
  filename: string
  mimetype: string
  page: number
  text: string
  score: number
  source_url?: string
  owner?: string
}

interface SearchResponse {
  results: SearchResult[]
  error?: string
}

function SearchPage() {

  const { selectedFilter, parsedFilterData } = useKnowledgeFilter()
  const [query, setQuery] = useState("")
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<SearchResult[]>([])
  const [searchPerformed, setSearchPerformed] = useState(false)
  const prevFilterDataRef = useRef<string>("")

  const handleSearch = useCallback(async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!query.trim()) return

    setLoading(true)
    setSearchPerformed(false)

    try {
      // Build search payload with global filter data
      interface SearchPayload {
        query: string;
        limit: number;
        scoreThreshold: number;
        filters?: {
          data_sources?: string[];
          document_types?: string[];
          owners?: string[];
        };
      }

      const searchPayload: SearchPayload = { 
        query,
        limit: parsedFilterData?.limit || 10,
        scoreThreshold: parsedFilterData?.scoreThreshold || 0
      }

      // Add filters from global context if available and not wildcards
      if (parsedFilterData?.filters) {
        const filters = parsedFilterData.filters
        
        // Only include filters if they're not wildcards (not "*")
        const hasSpecificFilters = 
          !filters.data_sources.includes("*") ||
          !filters.document_types.includes("*") ||
          !filters.owners.includes("*")

        if (hasSpecificFilters) {
          const processedFilters: SearchPayload['filters'] = {}
          
          // Only add filter arrays that don't contain wildcards
          if (!filters.data_sources.includes("*")) {
            processedFilters.data_sources = filters.data_sources
          }
          if (!filters.document_types.includes("*")) {
            processedFilters.document_types = filters.document_types
          }
          if (!filters.owners.includes("*")) {
            processedFilters.owners = filters.owners
          }

          // Only add filters object if it has any actual filters
          if (Object.keys(processedFilters).length > 0) {
            searchPayload.filters = processedFilters
          }
        }
        // If all filters are wildcards, omit the filters object entirely
      }

      const response = await fetch("/api/search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(searchPayload),
      })

      const result: SearchResponse = await response.json()
      
      if (response.ok) {
        setResults(result.results || [])
        setSearchPerformed(true)
      } else {
        console.error("Search failed:", result.error)
        setResults([])
        setSearchPerformed(true)
      }
    } catch (error) {
      console.error("Search error:", error)
      setResults([])
      setSearchPerformed(true)
    } finally {
      setLoading(false)
    }
  }, [query, parsedFilterData])

  // Update query when global filter changes
  useEffect(() => {
    if (parsedFilterData?.query) {
      setQuery(parsedFilterData.query)
    }
  }, [parsedFilterData])

  // Auto-refresh search when filter changes (but only if search was already performed)
  useEffect(() => {
    if (!parsedFilterData) return
    
    // Create a stable string representation of the filter data for comparison
    const currentFilterString = JSON.stringify({
      filters: parsedFilterData.filters,
      limit: parsedFilterData.limit,
      scoreThreshold: parsedFilterData.scoreThreshold
    })
    
    // Only trigger search if filter data actually changed and we've done a search before
    if (prevFilterDataRef.current !== "" && 
        prevFilterDataRef.current !== currentFilterString && 
        searchPerformed && 
        query.trim()) {
      
      console.log("Filter changed, auto-refreshing search")
      handleSearch()
    }
    
    // Update the ref with current filter data
    prevFilterDataRef.current = currentFilterString
  }, [parsedFilterData, searchPerformed, query, handleSearch])




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
            {selectedFilter && (
              <span className="text-sm font-normal text-blue-400 bg-blue-400/10 px-2 py-1 rounded">
                Filter: {selectedFilter.name}
              </span>
            )}
          </CardTitle>
          <CardDescription>
            Enter your search query to find relevant documents using hybrid search (semantic + keyword)
            {selectedFilter && (
              <span className="block text-blue-400 text-xs mt-1">
                Using knowledge filter: {selectedFilter.name}
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

          {/* Search Results */}
          {searchPerformed && (
            <div className="space-y-4">
              {/* Search Results Header */}
              <div className="flex justify-between items-center">
                <h2 className="text-2xl font-semibold flex items-center gap-2">
                  <Zap className="h-6 w-6 text-yellow-400" />
                  Search Results
                </h2>
                <div className="flex items-center gap-2">
                  <div className="h-2 w-2 bg-green-400 rounded-full animate-pulse"></div>
                  <span className="text-sm text-muted-foreground">
                    {results.length} result{results.length !== 1 ? 's' : ''} returned
                  </span>
                </div>
              </div>

              {/* Results */}
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
                          Try adjusting your search terms or modify your knowledge filter settings.
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
