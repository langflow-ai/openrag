"use client"

import React, { createContext, useContext, useState, ReactNode } from 'react'

export type EndpointType = 'chat' | 'langflow'

interface ConversationDocument {
  filename: string
  uploadTime: Date
}

interface ChatContextType {
  endpoint: EndpointType
  setEndpoint: (endpoint: EndpointType) => void
  currentConversationId: string | null
  setCurrentConversationId: (id: string | null) => void
  previousResponseIds: {
    chat: string | null
    langflow: string | null
  }
  setPreviousResponseIds: (ids: { chat: string | null; langflow: string | null }) => void
  refreshConversations: () => void
  refreshTrigger: number
  loadConversation: (conversation: any) => void
  startNewConversation: () => void
  conversationData: any
  forkFromResponse: (responseId: string, messagesToKeep: any[]) => void
  conversationDocs: ConversationDocument[]
  addConversationDoc: (filename: string) => void
  clearConversationDocs: () => void
}

const ChatContext = createContext<ChatContextType | undefined>(undefined)

interface ChatProviderProps {
  children: ReactNode
}

export function ChatProvider({ children }: ChatProviderProps) {
  const [endpoint, setEndpoint] = useState<EndpointType>('langflow')
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null)
  const [previousResponseIds, setPreviousResponseIds] = useState<{
    chat: string | null
    langflow: string | null
  }>({ chat: null, langflow: null })
  const [refreshTrigger, setRefreshTrigger] = useState(0)
  const [conversationData, setConversationData] = useState<any>(null)
  const [conversationDocs, setConversationDocs] = useState<ConversationDocument[]>([])

  const refreshConversations = () => {
    setRefreshTrigger(prev => prev + 1)
  }

  const loadConversation = (conversation: any) => {
    setCurrentConversationId(conversation.response_id)
    setEndpoint(conversation.endpoint)
    // Store the full conversation data for the chat page to use
    // We'll pass it through a ref or state that the chat page can access
    setConversationData(conversation)
  }

  const startNewConversation = () => {
    setCurrentConversationId(null)
    setPreviousResponseIds({ chat: null, langflow: null })
    setConversationData(null)
    setConversationDocs([])
  }

  const addConversationDoc = (filename: string) => {
    setConversationDocs(prev => [...prev, { filename, uploadTime: new Date() }])
  }

  const clearConversationDocs = () => {
    setConversationDocs([])
  }

  const forkFromResponse = (responseId: string, messagesToKeep: any[]) => {
    // Start a new conversation with the messages up to the fork point
    setCurrentConversationId(null) // Clear current conversation to indicate new conversation
    // Don't clear conversation data - let the chat page manage the messages
    // Set the response ID that we're forking from as the previous response ID
    setPreviousResponseIds(prev => ({
      ...prev,
      [endpoint]: responseId
    }))
    // The messages are already set by the chat page component before calling this
  }

  const value: ChatContextType = {
    endpoint,
    setEndpoint,
    currentConversationId,
    setCurrentConversationId,
    previousResponseIds,
    setPreviousResponseIds,
    refreshConversations,
    refreshTrigger,
    loadConversation,
    startNewConversation,
    conversationData,
    forkFromResponse,
    conversationDocs,
    addConversationDoc,
    clearConversationDocs,
  }

  return (
    <ChatContext.Provider value={value}>
      {children}
    </ChatContext.Provider>
  )
}

export function useChat(): ChatContextType {
  const context = useContext(ChatContext)
  if (context === undefined) {
    throw new Error('useChat must be used within a ChatProvider')
  }
  return context
}