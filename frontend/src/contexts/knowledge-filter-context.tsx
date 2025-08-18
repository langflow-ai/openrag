"use client"

import React, { createContext, useContext, useState, ReactNode } from 'react'

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

interface KnowledgeFilterContextType {
  selectedFilter: KnowledgeFilter | null
  parsedFilterData: ParsedQueryData | null
  setSelectedFilter: (filter: KnowledgeFilter | null) => void
  clearFilter: () => void
  isPanelOpen: boolean
  openPanel: () => void
  closePanel: () => void
  closePanelOnly: () => void
}

const KnowledgeFilterContext = createContext<KnowledgeFilterContextType | undefined>(undefined)

export function useKnowledgeFilter() {
  const context = useContext(KnowledgeFilterContext)
  if (context === undefined) {
    throw new Error('useKnowledgeFilter must be used within a KnowledgeFilterProvider')
  }
  return context
}

interface KnowledgeFilterProviderProps {
  children: ReactNode
}

export function KnowledgeFilterProvider({ children }: KnowledgeFilterProviderProps) {
  const [selectedFilter, setSelectedFilterState] = useState<KnowledgeFilter | null>(null)
  const [parsedFilterData, setParsedFilterData] = useState<ParsedQueryData | null>(null)
  const [isPanelOpen, setIsPanelOpen] = useState(false)

  const setSelectedFilter = (filter: KnowledgeFilter | null) => {
    setSelectedFilterState(filter)
    
    if (filter) {
      try {
        const parsed = JSON.parse(filter.query_data) as ParsedQueryData
        setParsedFilterData(parsed)
        
        // Auto-open panel when filter is selected
        setIsPanelOpen(true)
      } catch (error) {
        console.error('Error parsing filter data:', error)
        setParsedFilterData(null)
      }
    } else {
      setParsedFilterData(null)
      setIsPanelOpen(false)
    }
  }

  const clearFilter = () => {
    setSelectedFilter(null)
  }

  const openPanel = () => {
    setIsPanelOpen(true)
  }

  const closePanel = () => {
    setSelectedFilter(null) // This will also close the panel
  }

  const closePanelOnly = () => {
    setIsPanelOpen(false) // Close panel but keep filter selected
  }


  const value: KnowledgeFilterContextType = {
    selectedFilter,
    parsedFilterData,
    setSelectedFilter,
    clearFilter,
    isPanelOpen,
    openPanel,
    closePanel,
    closePanelOnly,
  }

  return (
    <KnowledgeFilterContext.Provider value={value}>
      {children}
    </KnowledgeFilterContext.Provider>
  )
}