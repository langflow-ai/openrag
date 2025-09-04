"use client"

import { useState, useEffect, useRef } from "react"
import { useRouter, usePathname } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Plus, MessageSquare, Database, Settings, GitBranch } from "lucide-react"
import { useChat } from "@/contexts/chat-context"
import { useAuth } from "@/contexts/auth-context"

interface Conversation {
  id: string
  title: string
  endpoint: string
  last_activity: string
  created_at: string
  response_id: string
  messages?: Array<{
    role: string
    content: string
    timestamp?: string
    response_id?: string
  }>
}

export function Navigation() {
  const router = useRouter()
  const pathname = usePathname()
  const { user } = useAuth()
  const {
    refreshTrigger,
    refreshTriggerSilent,
    loadConversation,
    startNewConversation,
    currentConversationId,
    placeholderConversation,
  } = useChat()
  
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [loading, setLoading] = useState(false)

  // Load conversations from backend
  const loadConversations = async () => {
    if (!user) return
    
    try {
      setLoading(true)
      const response = await fetch("/api/conversations")
      if (response.ok) {
        const data = await response.json()
        setConversations(data.conversations || [])
      }
    } catch (error) {
      console.error("Failed to load conversations:", error)
    } finally {
      setLoading(false)
    }
  }

  // Load conversations on mount and when refreshTrigger changes (with loading state)
  useEffect(() => {
    loadConversations()
  }, [refreshTrigger, user])

  // Silent refresh - update data without loading state
  useEffect(() => {
    const loadSilent = async () => {
      if (!user) return
      
      try {
        // Don't show loading state for silent refresh
        const response = await fetch("/api/conversations")
        if (response.ok) {
          const data = await response.json()
          setConversations(data.conversations || [])
        }
      } catch (error) {
        console.error("Silent conversation refresh failed:", error)
      }
    }

    // Only do silent refresh if we have a silent trigger change (not initial load)
    if (refreshTriggerSilent > 0) {
      loadSilent()
    }
  }, [refreshTriggerSilent, user])

  const handleNewConversation = () => {
    startNewConversation()
    // Dispatch custom event to notify chat page
    window.dispatchEvent(new CustomEvent('newConversation'))
    router.push('/chat')
  }

  const handleConversationClick = async (conversation: Conversation) => {
    try {
      // Load full conversation data from backend
      const response = await fetch(`/api/conversations/${conversation.response_id}`)
      if (response.ok) {
        const fullConversation = await response.json()
        loadConversation(fullConversation)
        router.push('/chat')
      }
    } catch (error) {
      console.error("Failed to load conversation:", error)
    }
  }

  const formatRelativeTime = (timestamp: string) => {
    const date = new Date(timestamp)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
    const diffDays = Math.floor(diffHours / 24)

    if (diffDays > 0) {
      return `${diffDays}d ago`
    } else if (diffHours > 0) {
      return `${diffHours}h ago`
    } else {
      return 'Just now'
    }
  }

  return (
    <nav className="flex flex-col h-full w-72 bg-muted/30 border-r border-border">
      {/* Header */}
      <div className="p-4 border-b border-border">
        <Button 
          onClick={handleNewConversation}
          className="w-full justify-start gap-2"
          variant="default"
        >
          <Plus className="h-4 w-4" />
          New Conversation
        </Button>
      </div>

      {/* Navigation Links */}
      <div className="p-4 border-b border-border">
        <div className="space-y-2">
          <Button
            variant={pathname === '/chat' ? 'secondary' : 'ghost'}
            className="w-full justify-start gap-2"
            onClick={() => router.push('/chat')}
          >
            <MessageSquare className="h-4 w-4" />
            Chat
          </Button>
          <Button
            variant={pathname === '/knowledge' ? 'secondary' : 'ghost'}
            className="w-full justify-start gap-2"
            onClick={() => router.push('/knowledge')}
          >
            <Database className="h-4 w-4" />
            Knowledge
          </Button>
          <Button
            variant={pathname === '/settings' ? 'secondary' : 'ghost'}
            className="w-full justify-start gap-2"
            onClick={() => router.push('/settings')}
          >
            <Settings className="h-4 w-4" />
            Settings
          </Button>
        </div>
      </div>

      {/* Conversations List */}
      <div className="flex-1 overflow-hidden">
        <div className="px-4 py-2">
          <h3 className="text-sm font-medium text-muted-foreground mb-2">Conversations</h3>
        </div>
        
        <div className="flex-1 overflow-y-auto px-2">
          {loading ? (
            <div className="p-4 text-sm text-muted-foreground">
              Loading conversations...
            </div>
          ) : (
            <div className="space-y-1">
              {/* Show placeholder conversation if exists */}
              {placeholderConversation && (
                <div className="p-2 rounded-md bg-primary/10 border border-primary/20">
                  <div className="flex items-center gap-2 text-sm">
                    <MessageSquare className="h-3 w-3 text-primary" />
                    <span className="text-primary font-medium">New conversation</span>
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    Active
                  </div>
                </div>
              )}
              
              {conversations.map((conversation) => (
                <button
                  key={conversation.id}
                  onClick={() => handleConversationClick(conversation)}
                  className={`w-full text-left p-2 rounded-md transition-colors hover:bg-muted/50 ${
                    currentConversationId === conversation.response_id 
                      ? 'bg-muted border border-border' 
                      : ''
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <MessageSquare className="h-3 w-3 text-muted-foreground" />
                    <span className="text-sm font-medium truncate">
                      {conversation.title || 'Untitled'}
                    </span>
                    {conversation.endpoint === 'chat' && (
                      <GitBranch className="h-3 w-3 text-blue-400 ml-auto" />
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {formatRelativeTime(conversation.last_activity)}
                  </div>
                </button>
              ))}
              
              {conversations.length === 0 && !placeholderConversation && (
                <div className="p-4 text-sm text-muted-foreground text-center">
                  No conversations yet
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </nav>
  )
}