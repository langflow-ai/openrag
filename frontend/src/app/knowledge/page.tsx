"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { useRouter } from "next/navigation"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Search, Loader2, FileText, HardDrive, Building2, Cloud, Plus } from "lucide-react"
import { TbBrandOnedrive } from "react-icons/tb"
import { SiGoogledrive } from "react-icons/si"
import { ProtectedRoute } from "@/components/protected-route"
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context"
import { useTask } from "@/contexts/task-context"
import { KnowledgeDropdown } from "@/components/knowledge-dropdown"

type FacetBucket = { key: string; count: number }

interface ChunkResult {
  filename: string
  mimetype: string
  page: number
  text: string
  score: number
  source_url?: string
  owner?: string
  owner_name?: string
  owner_email?: string
  file_size?: number
  connector_type?: string
}

interface FileResult {
  filename: string
  mimetype: string
  chunkCount: number
  avgScore: number
  source_url?: string
  owner?: string
  owner_name?: string
  owner_email?: string
  lastModified?: string
  size?: number
  connector_type?: string
}

interface SearchResponse {
  results: ChunkResult[]
  files?: FileResult[]
  error?: string
  total?: number
  aggregations?: {
    data_sources?: { buckets?: Array<{ key: string | number; doc_count: number }> }
    document_types?: { buckets?: Array<{ key: string | number; doc_count: number }> }
    owners?: { buckets?: Array<{ key: string | number; doc_count: number }> }
    connector_types?: { buckets?: Array<{ key: string | number; doc_count: number }> }
  }
}

// Function to get the appropriate icon for a connector type
function getSourceIcon(connectorType?: string) {
  switch (connectorType) {
    case 'google_drive':
      return <SiGoogledrive className="h-4 w-4 text-foreground" />
    case 'onedrive':
      return <TbBrandOnedrive className="h-4 w-4 text-foreground" />
    case 'sharepoint':
      return <Building2 className="h-4 w-4 text-foreground" />
    case 's3':
      return <Cloud className="h-4 w-4 text-foreground" />
    case 'local':
    default:
      return <HardDrive className="h-4 w-4 text-muted-foreground" />
  }
}

function SearchPage() {
  const router = useRouter()
  const { isMenuOpen } = useTask()
  const { parsedFilterData, isPanelOpen } = useKnowledgeFilter()
  const [query, setQuery] = useState("*")
  const [loading, setLoading] = useState(false)
  const [chunkResults, setChunkResults] = useState<ChunkResult[]>([])
  const [fileResults, setFileResults] = useState<FileResult[]>([])
  const [viewMode, setViewMode] = useState<'files' | 'chunks'>('files')
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [searchPerformed, setSearchPerformed] = useState(false)
  const prevFilterDataRef = useRef<string>("")

  // Stats state for knowledge overview
  const [statsLoading, setStatsLoading] = useState<boolean>(false)
  const [totalDocs, setTotalDocs] = useState<number>(0)
  const [totalChunks, setTotalChunks] = useState<number>(0)
  const [facetStats, setFacetStats] = useState<{ data_sources: FacetBucket[]; document_types: FacetBucket[]; owners: FacetBucket[]; connector_types: FacetBucket[] } | null>(null)

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
          connector_types?: string[];
        };
      }

      const searchPayload: SearchPayload = { 
        query,
        limit: parsedFilterData?.limit || (query.trim() === "*" ? 50 : 10),  // Higher limit for wildcard searches
        scoreThreshold: parsedFilterData?.scoreThreshold || 0
      }

      // Debug logging for wildcard searches
      if (query.trim() === "*") {
        console.log("Wildcard search - parsedFilterData:", parsedFilterData)
      }

      // Add filters from global context if available and not wildcards
      if (parsedFilterData?.filters) {
        const filters = parsedFilterData.filters
        
        // Only include filters if they're not wildcards (not "*")
        const hasSpecificFilters = 
          !filters.data_sources.includes("*") ||
          !filters.document_types.includes("*") ||
          !filters.owners.includes("*") ||
          (filters.connector_types && !filters.connector_types.includes("*"))

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
          if (filters.connector_types && !filters.connector_types.includes("*")) {
            processedFilters.connector_types = filters.connector_types
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
        const chunks = result.results || []
        
        // Debug logging for wildcard searches
        if (query.trim() === "*") {
          console.log("Wildcard search results:", {
            chunks: chunks.length,
            totalFromBackend: result.total,
            searchPayload,
            firstChunk: chunks[0]
          })
        }
        
        setChunkResults(chunks)
        
        // Group chunks by filename to create file results
        const fileMap = new Map<string, {
          filename: string
          mimetype: string
          chunks: ChunkResult[]
          totalScore: number
          source_url?: string
          owner?: string
          owner_name?: string
          owner_email?: string
          file_size?: number
          connector_type?: string
        }>()
        
        chunks.forEach(chunk => {
          const existing = fileMap.get(chunk.filename)
          if (existing) {
            existing.chunks.push(chunk)
            existing.totalScore += chunk.score
          } else {
            fileMap.set(chunk.filename, {
              filename: chunk.filename,
              mimetype: chunk.mimetype,
              chunks: [chunk],
              totalScore: chunk.score,
              source_url: chunk.source_url,
              owner: chunk.owner,
              owner_name: chunk.owner_name,
              owner_email: chunk.owner_email,
              file_size: chunk.file_size,
              connector_type: chunk.connector_type
            })
          }
        })
        
        const files: FileResult[] = Array.from(fileMap.values()).map(file => ({
          filename: file.filename,
          mimetype: file.mimetype,
          chunkCount: file.chunks.length,
          avgScore: file.totalScore / file.chunks.length,
          source_url: file.source_url,
          owner: file.owner,
          owner_name: file.owner_name,
          owner_email: file.owner_email,
          size: file.file_size,
          connector_type: file.connector_type
        }))
        
        setFileResults(files)
        setSearchPerformed(true)
      } else {
        console.error("Search failed:", result.error)
        setChunkResults([])
        setFileResults([])
        setSearchPerformed(true)
      }
    } catch (error) {
      console.error("Search error:", error)
      setChunkResults([])
      setFileResults([])
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
  const fetchStats = useCallback(async () => {
    try {
      setStatsLoading(true)
      
      // Build search payload with current filter data
      interface SearchPayload {
        query: string;
        limit: number;
        scoreThreshold: number;
        filters?: {
          data_sources?: string[];
          document_types?: string[];
          owners?: string[];
          connector_types?: string[];
        };
      }

      const searchPayload: SearchPayload = { 
        query: '*', 
        limit: 50, // Get more results to ensure we have owner mapping data
        scoreThreshold: parsedFilterData?.scoreThreshold || 0
      }

      // Add filters from global context if available and not wildcards
      if (parsedFilterData?.filters) {
        const filters = parsedFilterData.filters
        
        // Only include filters if they're not wildcards (not "*")
        const hasSpecificFilters = 
          !filters.data_sources.includes("*") ||
          !filters.document_types.includes("*") ||
          !filters.owners.includes("*") ||
          (filters.connector_types && !filters.connector_types.includes("*"))

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
          if (filters.connector_types && !filters.connector_types.includes("*")) {
            processedFilters.connector_types = filters.connector_types
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
        
        // Now we can aggregate directly on owner names since they're keyword fields
        
        const dataSourceBuckets = toBuckets(aggs.data_sources)
        setFacetStats({
          data_sources: dataSourceBuckets.slice(0, 10),
          document_types: toBuckets(aggs.document_types).slice(0, 10),
          owners: toBuckets(aggs.owners).slice(0, 10),
          connector_types: toBuckets(aggs.connector_types || {}).slice(0, 10)
        })
        setTotalDocs(dataSourceBuckets.length)
        setTotalChunks(Number(result.total || 0))
      }
    } catch {
      // non-fatal – keep page functional without stats
    } finally {
      setStatsLoading(false)
    }
  }, [parsedFilterData])

  // Auto-search on mount with "*"
  useEffect(() => {
    if (query === "*") {
      handleSearch()
    }
  }, []) // Only run once on mount
  
  // Initial stats fetch and refresh when filter changes
  useEffect(() => {
    fetchStats()
  }, [fetchStats])




  return (
    <div className={`fixed inset-0 md:left-72 top-[53px] flex flex-col transition-all duration-300 ${
      isMenuOpen && isPanelOpen ? 'md:right-[704px]' : // Both open: 384px (menu) + 320px (KF panel)
      isMenuOpen ? 'md:right-96' : // Only menu open: 384px
      isPanelOpen ? 'md:right-80' : // Only KF panel open: 320px
      'md:right-6' // Neither open: 24px
    }`}>
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
            <div className="flex-shrink-0">
              <KnowledgeDropdown variant="button" />
            </div>
          </form>
        </div>

        {/* Results Area */}
        <div className="flex-1 overflow-y-auto">
          <div className="space-y-4">
            {fileResults.length === 0 && chunkResults.length === 0 && !loading ? (
              <div className="text-center py-12">
                <Search className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                <p className="text-lg text-muted-foreground">No documents found</p>
                <p className="text-sm text-muted-foreground/70 mt-2">
                  Try adjusting your search terms
                </p>
              </div>
            ) : (
              <>
                {/* Results Count */}
                <div className="mb-4">
                  <div className="text-sm text-muted-foreground">
                    {fileResults.length} file{fileResults.length !== 1 ? 's' : ''} found
                  </div>
                </div>

                {/* Results Display */}
                <div className="space-y-4">
                  {viewMode === 'files' ? (
                    selectedFile ? (
                      // Show chunks for selected file
                      <>
                        <div className="flex items-center gap-2 mb-4">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setSelectedFile(null)}
                          >
                            ← Back to files
                          </Button>
                          <span className="text-sm text-muted-foreground">
                            Chunks from {selectedFile}
                          </span>
                        </div>
                        {chunkResults
                          .filter(chunk => chunk.filename === selectedFile)
                          .map((chunk, index) => (
                          <div key={index} className="bg-muted/20 rounded-lg p-4 border border-border/50">
                            <div className="flex items-center justify-between mb-2">
                              <div className="flex items-center gap-2">
                                <FileText className="h-4 w-4 text-blue-400" />
                                <span className="font-medium truncate">{chunk.filename}</span>
                              </div>
                              <span className="text-xs text-green-400 bg-green-400/20 px-2 py-1 rounded">
                                {chunk.score.toFixed(2)}
                              </span>
                            </div>
                            <div className="text-sm text-muted-foreground mb-2">
                              {chunk.mimetype} • Page {chunk.page}
                            </div>
                            <p className="text-sm text-foreground/90 leading-relaxed">
                              {chunk.text}
                            </p>
                          </div>
                        ))}
                      </>
                    ) : (
                      // Show files table
                      <div className="bg-muted/20 rounded-lg border border-border/50 overflow-hidden">
                        <table className="w-full">
                          <thead>
                            <tr className="border-b border-border/50 bg-muted/10">
                              <th className="text-left p-3 text-sm font-medium text-muted-foreground">Source</th>
                              <th className="text-left p-3 text-sm font-medium text-muted-foreground">Type</th>
                              <th className="text-left p-3 text-sm font-medium text-muted-foreground">Size</th>
                              <th className="text-left p-3 text-sm font-medium text-muted-foreground">Matching chunks</th>
                              <th className="text-left p-3 text-sm font-medium text-muted-foreground">Average score</th>
                              <th className="text-left p-3 text-sm font-medium text-muted-foreground">Owner</th>
                            </tr>
                          </thead>
                          <tbody>
                            {fileResults.map((file, index) => (
                              <tr
                                key={index}
                                className="border-b border-border/30 hover:bg-muted/20 cursor-pointer transition-colors"
                                onClick={() => setSelectedFile(file.filename)}
                              >
                                <td className="p-3">
                                  <div className="flex items-center gap-2">
                                    {getSourceIcon(file.connector_type)}
                                    <span className="font-medium truncate" title={file.filename}>
                                      {file.filename}
                                    </span>
                                  </div>
                                </td>
                                <td className="p-3 text-sm text-muted-foreground">
                                  {file.mimetype}
                                </td>
                                <td className="p-3 text-sm text-muted-foreground">
                                  {file.size ? `${Math.round(file.size / 1024)} KB` : '—'}
                                </td>
                                <td className="p-3 text-sm text-muted-foreground">
                                  {file.chunkCount}
                                </td>
                                <td className="p-3">
                                  <span className="text-xs text-green-400 bg-green-400/20 px-2 py-1 rounded">
                                    {file.avgScore.toFixed(2)}
                                  </span>
                                </td>
                                <td className="p-3 text-sm text-muted-foreground" title={file.owner_email}>
                                  {file.owner_name || file.owner || '—'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )
                  ) : (
                    // Show chunks view
                    chunkResults.map((result, index) => (
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
                    ))
                  )}
                </div>
              </>
            )}
          </div>
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
