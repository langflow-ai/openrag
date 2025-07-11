"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Search, Loader2, FileText } from "lucide-react"

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
    <div className="max-w-4xl mx-auto space-y-8">
      <div className="text-center">
        <h1 className="text-3xl font-bold tracking-tight">Document Search</h1>
        <p className="text-muted-foreground mt-2">Search through your indexed documents</p>
      </div>

      <Card className="max-w-2xl w-full mx-auto">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-5 w-5" />
            Search Documents
          </CardTitle>
          <CardDescription>
            Enter your search query to find relevant documents
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSearch} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="search-query">Search Query</Label>
              <Input
                id="search-query"
                type="text"
                placeholder="Enter your search terms..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="text-base"
              />
            </div>
            <Button
              type="submit"
              disabled={!query.trim() || loading}
              className="w-full"
            >
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Searching...
                </>
              ) : (
                <>
                  <Search className="mr-2 h-4 w-4" />
                  Search
                </>
              )}
            </Button>
          </form>
          {/* Always render the results area, but show it empty if no search has been performed */}
          <div className="mt-8">
            {searchPerformed ? (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-xl font-semibold">Search Results</h2>
                  <span className="text-sm text-muted-foreground">
                    {results.length} result{results.length !== 1 ? 's' : ''} found
                  </span>
                </div>
                {results.length === 0 ? (
                  <Card>
                    <CardContent className="pt-6">
                      <p className="text-center text-muted-foreground">
                        No documents found matching your search query.
                      </p>
                    </CardContent>
                  </Card>
                ) : (
                  <div className="space-y-4">
                    {results.map((result, index) => (
                      <Card key={index}>
                        <CardHeader className="pb-3">
                          <div className="flex items-center justify-between">
                            <CardTitle className="text-lg flex items-center gap-2">
                              <FileText className="h-4 w-4" />
                              {result.filename}
                            </CardTitle>
                            <div className="text-sm text-muted-foreground">
                              Score: {result.score.toFixed(2)}
                            </div>
                          </div>
                          <CardDescription>
                            Type: {result.mimetype} • Page {result.page}
                          </CardDescription>
                        </CardHeader>
                        <CardContent>
                          <div className="border-l-2 border-primary pl-4">
                            <p className="text-sm leading-relaxed">
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
              <div style={{ minHeight: 120 }} />
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
