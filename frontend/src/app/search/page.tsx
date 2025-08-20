"use client"

import { useState, useEffect, useCallback, useRef } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Search, Loader2, FileText, Zap, RefreshCw } from "lucide-react"
import { ProtectedRoute } from "@/components/protected-route"
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context"

type FacetBucket = { key: string; count: number }

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

  // Stats state for knowledge overview
  const [statsLoading, setStatsLoading] = useState<boolean>(false)
  const [totalDocs, setTotalDocs] = useState<number>(0)
  const [totalChunks, setTotalChunks] = useState<number>(0)
  const [facetStats, setFacetStats] = useState<{ data_sources: FacetBucket[]; document_types: FacetBucket[]; owners: FacetBucket[] } | null>(null)

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

  // Fetch stats with current knowledge filter applied
  const fetchStats = async () => {
    try {
      setStatsLoading(true)
      
      // Build search payload with current filter data
      const searchPayload: any = { 
        query: '*', 
        limit: 0,
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
          const processedFilters: any = {}
          
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
      }

      const response = await fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(searchPayload)
      })
      const result = await response.json()
      if (response.ok) {
        const aggs = result.aggregations || {}
        const toBuckets = (agg: { buckets?: Array<{ key: string | number; doc_count: number }> }): FacetBucket[] =>
          (agg?.buckets || []).map(b => ({ key: String(b.key), count: b.doc_count }))
        const dataSourceBuckets = toBuckets(aggs.data_sources)
        setFacetStats({
          data_sources: dataSourceBuckets.slice(0, 10),
          document_types: toBuckets(aggs.document_types).slice(0, 10),
          owners: toBuckets(aggs.owners).slice(0, 10)
        })
        setTotalDocs(dataSourceBuckets.length)
        setTotalChunks(Number(result.total || 0))
      }
    } catch {
      // non-fatal – keep page functional without stats
    } finally {
      setStatsLoading(false)
    }
  }

  // Initial stats fetch and refresh when filter changes
  useEffect(() => {
    fetchStats()
  }, [parsedFilterData])




  return (
    <div className="fixed inset-0 md:left-72 md:right-6 top-[53px] flex flex-col">
      <div className="flex-1 flex flex-col min-h-0 px-6 py-6">
        {/* Search Input Area */}
        <div className="flex-shrink-0 mb-6">
          <form onSubmit={handleSearch} className="flex gap-3">
            <Input
              id="search-query"
              type="text"
              placeholder="Search your documents..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="flex-1 bg-muted/20 rounded-lg border border-border/50 px-4 py-3 h-12 focus-visible:ring-1 focus-visible:ring-ring"
            />
            <Button
              type="submit"
              disabled={!query.trim() || loading}
              variant="secondary"
              className="rounded-lg h-12 w-12 p-0 flex-shrink-0"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
            </Button>
          </form>
        </div>

        {/* Results Area */}
        <div className="flex-1 overflow-y-auto">
          {searchPerformed ? (
            <div className="space-y-4">
              {results.length === 0 ? (
                <div className="text-center py-12">
                  <Search className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                  <p className="text-lg text-muted-foreground">No documents found</p>
                  <p className="text-sm text-muted-foreground/70 mt-2">
                    Try adjusting your search terms
                  </p>
                </div>
              ) : (
                <>
                  <div className="text-sm text-muted-foreground mb-4">
                    {results.length} result{results.length !== 1 ? 's' : ''} found
                  </div>
                  <div className="space-y-4">
                    {results.map((result, index) => (
                      <div key={index} className="bg-muted/20 rounded-lg p-4 border border-border/50">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <FileText className="h-4 w-4 text-blue-400" />
                            <span className="font-medium truncate">{result.filename}</span>
                          </div>
                          <span className="text-xs text-green-400 bg-green-400/20 px-2 py-1 rounded">
                            {result.score.toFixed(2)}
                          </span>
                        </div>
                        <div className="text-sm text-muted-foreground mb-2">
                          {result.mimetype} • Page {result.page}
                        </div>
                        <p className="text-sm text-foreground/90 leading-relaxed">
                          {result.text}
                        </p>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          ) : (
            /* Knowledge Overview - Show when no search has been performed */
            <div className="bg-muted/20 rounded-lg border border-border/50">
              <div className="p-6">
                <div className="mb-6">
                  <h2 className="text-lg font-semibold">Knowledge Overview</h2>
                </div>

                {/* Documents row */}
                <div className="mb-6">
                  <div className="text-sm text-muted-foreground mb-1">Total documents</div>
                  <div className="text-2xl font-semibold">{statsLoading ? '—' : totalDocs}</div>
                </div>

                {/* Separator */}
                <div className="border-t border-border/50 my-6" />

                {/* Chunks and breakdown */}
                <div className="grid gap-6 md:grid-cols-4">
                  <div>
                    <div className="text-sm text-muted-foreground mb-1">Total chunks</div>
                    <div className="text-2xl font-semibold">{statsLoading ? '—' : totalChunks}</div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground mb-2">Top types</div>
                    <div className="flex flex-wrap gap-2">
                      {(facetStats?.document_types || []).slice(0,5).map((b) => (
                        <Badge key={`type-${b.key}`} variant="secondary">{b.key} · {b.count}</Badge>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground mb-2">Top owners</div>
                    <div className="flex flex-wrap gap-2">
                      {(facetStats?.owners || []).slice(0,5).map((b) => (
                        <Badge key={`owner-${b.key}`} variant="secondary">{b.key || 'unknown'} · {b.count}</Badge>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground mb-2">Top files</div>
                    <div className="flex flex-wrap gap-2">
                      {(facetStats?.data_sources || []).slice(0,5).map((b) => (
                        <Badge key={`file-${b.key}`} variant="secondary" title={b.key}>{b.key} · {b.count}</Badge>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
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
