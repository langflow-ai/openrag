"use client"

import React, { createContext, useContext, useState, ReactNode } from 'react'

export type EndpointType = 'chat' | 'langflow'

interface ConversationDocument {
  filename: string
  uploadTime: Date
}

interface ConversationMessage {
  role: string
  content: string
  timestamp?: string
  response_id?: string
}

interface ConversationData {
  messages: ConversationMessage[]
  endpoint: EndpointType
  response_id: string
  [key: string]: unknown
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
  loadConversation: (conversation: ConversationData) => void
  startNewConversation: () => void
  conversationData: ConversationData | null
  forkFromResponse: (responseId: string) => void
  conversationDocs: ConversationDocument[]
  addConversationDoc: (filename: string) => void
  clearConversationDocs: () => void
  placeholderConversation: ConversationData | null
  setPlaceholderConversation: (conversation: ConversationData | null) => void
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
  const [conversationData, setConversationData] = useState<ConversationData | null>(null)
  const [conversationDocs, setConversationDocs] = useState<ConversationDocument[]>([])
  const [placeholderConversation, setPlaceholderConversation] = useState<ConversationData | null>(null)

  const refreshConversations = () => {
    setRefreshTrigger(prev => prev + 1)
  }

  const loadConversation = (conversation: ConversationData) => {
    setCurrentConversationId(conversation.response_id)
    setEndpoint(conversation.endpoint)
    // Store the full conversation data for the chat page to use
    // We'll pass it through a ref or state that the chat page can access
    setConversationData(conversation)
    // Clear placeholder when loading a real conversation
    setPlaceholderConversation(null)
  }

  const startNewConversation = () => {
    // Create a temporary placeholder conversation
    const placeholderConversation: ConversationData = {
      response_id: 'new-conversation-' + Date.now(),
      title: 'New conversation',
      endpoint: endpoint,
      messages: [{
        role: 'assistant',
        content: 'How can I assist?',
        timestamp: new Date().toISOString()
      }],
      created_at: new Date().toISOString(),
      last_activity: new Date().toISOString()
    }
    
    setCurrentConversationId(null)
    setPreviousResponseIds({ chat: null, langflow: null })
    setConversationData(null)
    setConversationDocs([])
    setPlaceholderConversation(placeholderConversation)
    // Force a refresh to ensure sidebar shows correct state
    setRefreshTrigger(prev => prev + 1)
  }

  const addConversationDoc = (filename: string) => {
    setConversationDocs(prev => [...prev, { filename, uploadTime: new Date() }])
  }

  const clearConversationDocs = () => {
    setConversationDocs([])
  }

  const forkFromResponse = (responseId: string) => {
    // Start a new conversation with the messages up to the fork point
    setCurrentConversationId(null) // Clear current conversation to indicate new conversation
    setConversationData(null) // Clear conversation data to prevent reloading
    // Set the response ID that we're forking from as the previous response ID
    setPreviousResponseIds(prev => ({
      ...prev,
      [endpoint]: responseId
    }))
    // Clear placeholder when forking
    setPlaceholderConversation(null)
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
    placeholderConversation,
    setPlaceholderConversation,
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