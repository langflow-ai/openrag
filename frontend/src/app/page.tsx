"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Search, Loader2, FileText, Database, Zap } from "lucide-react"

interface SearchResult {
  filename: string
  mimetype: string
  page: number
  text: string
  score: number
}

export default function SearchPage() {
  const [query, setQuery] = useState("")
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<SearchResult[]>([])
  const [searchPerformed, setSearchPerformed] = useState(false)

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim()) return

    setLoading(true)
    setSearchPerformed(false)

    try {
      const response = await fetch("/api/search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ query }),
      })

      const result = await response.json()
      
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
          Find documents using semantic search
        </p>
        <p className="text-sm text-muted-foreground max-w-2xl">
          Enter your search query to find relevant documents using AI-powered semantic search across your document collection.
        </p>
      </div>

      {/* Search Interface */}
      <Card className="w-full bg-card/50 backdrop-blur-sm border-border/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-5 w-5" />
            Search Documents
          </CardTitle>
          <CardDescription>
            Enter your search query to find relevant documents using semantic search
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <form onSubmit={handleSearch} className="space-y-4">
            <div className="space-y-3">
              <Label htmlFor="search-query" className="font-medium">
                Search Query
              </Label>
              <Input
                id="search-query"
                type="text"
                placeholder="e.g., 'financial reports from Q4' or 'user authentication setup'"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="h-12 bg-background/50 border-border/50 focus:border-blue-400/50 focus:ring-blue-400/20"
              />
            </div>
            <Button
              type="submit"
              disabled={!query.trim() || loading}
              className="w-full h-12 transition-all duration-200"
            >
              {loading ? (
                <>
                  <Loader2 className="mr-3 h-5 w-5 animate-spin" />
                  Searching...
                </>
              ) : (
                <>
                  <Search className="mr-3 h-5 w-5" />
                  Search Documents
                </>
              )}
            </Button>
          </form>

          {/* Results Section */}
          <div className="mt-8">
            {searchPerformed ? (
              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <h2 className="text-2xl font-semibold flex items-center gap-2">
                    <Zap className="h-6 w-6 text-yellow-400" />
                    Search Results
                  </h2>
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-2 bg-green-400 rounded-full animate-pulse"></div>
                    <span className="text-sm text-muted-foreground">
                      {results.length} result{results.length !== 1 ? 's' : ''} found
                    </span>
                  </div>
                </div>
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
            ) : (
              <div className="h-32 flex items-center justify-center">
                <p className="text-muted-foreground/50 text-sm">
                  Enter a search query above to get started
                </p>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
