"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Search, Loader2, BookOpenCheck, Settings, Calendar, MessageCircle } from "lucide-react"
import { ProtectedRoute } from "@/components/protected-route"

interface KnowledgeFilter {
  id: string
  name: string
  description: string
  query_data: string
  owner: string
  created_at: string
  updated_at: string
}

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

function KnowledgeFiltersPage() {
  const router = useRouter()
  const [filters, setFilters] = useState<KnowledgeFilter[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState("")
  const [selectedFilter, setSelectedFilter] = useState<KnowledgeFilter | null>(null)
  const [parsedQueryData, setParsedQueryData] = useState<ParsedQueryData | null>(null)

  const loadFilters = async (query = "") => {
    setLoading(true)
    try {
      const response = await fetch("/api/knowledge-filter/search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query,
          limit: 50
        }),
      })

      const result = await response.json()
      if (response.ok && result.success) {
        setFilters(result.filters)
      } else {
        console.error("Failed to load knowledge filters:", result.error)
        setFilters([])
      }
    } catch (error) {
      console.error("Error loading knowledge filters:", error)
      setFilters([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadFilters()
  }, [])

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault()
    await loadFilters(searchQuery)
  }

  const handleFilterClick = (filter: KnowledgeFilter) => {
    setSelectedFilter(filter)
    try {
      const parsed = JSON.parse(filter.query_data) as ParsedQueryData
      setParsedQueryData(parsed)
    } catch (error) {
      console.error("Error parsing query data:", error)
      setParsedQueryData(null)
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

  const handleSearchWithFilter = () => {
    if (!selectedFilter) return
    
    router.push(`/?filterId=${selectedFilter.id}`)
  }

  const handleChatWithFilter = () => {
    if (!selectedFilter) return
    
    router.push(`/chat?filterId=${selectedFilter.id}`)
  }

  return (
    <div className="space-y-8">
      {/* Hero Section */}
      <div className="space-y-4">
        <div className="mb-4">
          <h1 className="text-4xl font-bold tracking-tight text-white">
            Knowledge Filters
          </h1>
        </div>
        <p className="text-xl text-muted-foreground">
          Manage your saved knowledge filters
        </p>
        <p className="text-sm text-muted-foreground max-w-2xl">
          View and manage your saved search configurations that help you focus on specific subsets of your knowledge base.
        </p>
      </div>

      {/* Search Interface */}
      <Card className="w-full bg-card/50 backdrop-blur-sm border-border/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BookOpenCheck className="h-5 w-5" />
            Search Knowledge Filters
          </CardTitle>
          <CardDescription>
            Search through your saved knowledge filters by name or description
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <form onSubmit={handleSearch} className="space-y-4">
            <div className="flex gap-2">
              <Input
                type="text"
                placeholder="Search knowledge filters..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-12 bg-background/50 border-border/50 focus:border-blue-400/50 focus:ring-blue-400/20 flex-1"
              />
              <Button
                type="submit"
                disabled={loading}
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
          </form>

          <div className="flex gap-6">
            {/* Context List */}
            <div className="flex-1 space-y-4">
              {filters.length === 0 ? (
                <Card className="bg-muted/20 border-dashed border-muted-foreground/30">
                  <CardContent className="pt-8 pb-8">
                    <div className="text-center space-y-3">
                      <div className="mx-auto w-16 h-16 bg-muted/30 rounded-full flex items-center justify-center">
                        <BookOpenCheck className="h-8 w-8 text-muted-foreground/50" />
                      </div>
                      <p className="text-lg font-medium text-muted-foreground">
                        No knowledge filters found
                      </p>
                      <p className="text-sm text-muted-foreground/70 max-w-md mx-auto">
                        Create your first knowledge filter by saving a search configuration from the search page.
                      </p>
                    </div>
                  </CardContent>
                </Card>
              ) : (
                <div className="space-y-3">
                  {filters.map((filter) => (
                    <Card
                      key={filter.id}
                      className={`bg-card/50 backdrop-blur-sm border-border/50 hover:bg-card/70 transition-all duration-200 hover:shadow-lg hover:shadow-blue-500/10 cursor-pointer ${
                        selectedFilter?.id === filter.id ? 'ring-2 ring-blue-500/50 bg-card/70' : ''
                      }`}
                      onClick={() => handleFilterClick(filter)}
                    >
                      <CardContent className="p-4">
                        <div className="flex items-start justify-between">
                          <div className="flex-1 space-y-2">
                            <h3 className="font-semibold text-lg">{filter.name}</h3>
                            {filter.description && (
                              <p className="text-sm text-muted-foreground">{filter.description}</p>
                            )}
                            <div className="flex items-center gap-4 text-xs text-muted-foreground">
                              <div className="flex items-center gap-1">
                                <Calendar className="h-3 w-3" />
                                <span>Created {formatDate(filter.created_at)}</span>
                              </div>
                              {filter.updated_at !== filter.created_at && (
                                <div className="flex items-center gap-1">
                                  <Calendar className="h-3 w-3" />
                                  <span>Updated {formatDate(filter.updated_at)}</span>
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </div>

            {/* Context Detail Panel */}
            {selectedFilter && parsedQueryData && (
              <div className="w-64 space-y-6 flex-shrink-0">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold flex items-center gap-2">
                    <Settings className="h-5 w-5" />
                    Knowledge Filter Details
                  </h2>
                </div>

                <div className="space-y-6">
                  {/* Query Information */}
                  <div className="space-y-2">
                    <Label className="text-sm font-medium">Query</Label>
                    <div className="p-3 bg-muted/50 rounded-md">
                      <p className="text-sm">{parsedQueryData.query}</p>
                    </div>
                  </div>

                  {/* Filters */}
                  {(parsedQueryData.filters.data_sources.length > 0 || 
                    parsedQueryData.filters.document_types.length > 0 || 
                    parsedQueryData.filters.owners.length > 0) && (
                    <div className="space-y-4">
                      <Label className="text-sm font-medium">Filters</Label>
                      
                      {parsedQueryData.filters.data_sources.length > 0 && (
                        <div className="space-y-2">
                          <Label className="text-xs text-muted-foreground">Data Sources</Label>
                          <div className="space-y-1">
                            {parsedQueryData.filters.data_sources.map((source, index) => (
                              <div key={index} className="px-2 py-1 bg-muted/30 rounded text-xs">
                                {source}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {parsedQueryData.filters.document_types.length > 0 && (
                        <div className="space-y-2">
                          <Label className="text-xs text-muted-foreground">Document Types</Label>
                          <div className="space-y-1">
                            {parsedQueryData.filters.document_types.map((type, index) => (
                              <div key={index} className="px-2 py-1 bg-muted/30 rounded text-xs">
                                {type}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {parsedQueryData.filters.owners.length > 0 && (
                        <div className="space-y-2">
                          <Label className="text-xs text-muted-foreground">Owners</Label>
                          <div className="space-y-1">
                            {parsedQueryData.filters.owners.map((owner, index) => (
                              <div key={index} className="px-2 py-1 bg-muted/30 rounded text-xs">
                                {owner}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Search Settings */}
                  <div className="space-y-4 pt-4 border-t border-border/50">
                    <Label className="text-sm font-medium">Search Settings</Label>
                    
                    <div className="space-y-3">
                      <div className="flex justify-between items-center">
                        <Label className="text-xs text-muted-foreground">Limit</Label>
                        <span className="text-sm font-mono">{parsedQueryData.limit}</span>
                      </div>
                      
                      <div className="flex justify-between items-center">
                        <Label className="text-xs text-muted-foreground">Score Threshold</Label>
                        <span className="text-sm font-mono">{parsedQueryData.scoreThreshold}</span>
                      </div>
                    </div>
                  </div>

                  {/* Action Buttons */}
                  <div className="space-y-2 pt-4 border-t border-border/50">
                    <Button
                      onClick={handleSearchWithFilter}
                      className="w-full flex items-center gap-2"
                      variant="default"
                    >
                      <Search className="h-4 w-4" />
                      Search with Filter
                    </Button>
                    
                    <Button
                      onClick={handleChatWithFilter}
                      className="w-full flex items-center gap-2"
                      variant="outline"
                    >
                      <MessageCircle className="h-4 w-4" />
                      Chat with Filter
                    </Button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export default function ProtectedKnowledgeFiltersPage() {
  return (
    <ProtectedRoute>
      <KnowledgeFiltersPage />
    </ProtectedRoute>
  )
}