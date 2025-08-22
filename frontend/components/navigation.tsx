"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Library, MessageSquare, Settings2, Plus, FileText } from "lucide-react"
import { cn } from "@/lib/utils"
import { useState, useEffect, useRef } from "react"
import { useChat } from "@/contexts/chat-context"

interface ChatConversation {
  response_id: string
  title: string
  endpoint: 'chat' | 'langflow'
  messages: Array<{
    role: 'user' | 'assistant'
    content: string
    timestamp?: string
    response_id?: string
  }>
  created_at?: string
  last_activity?: string
  previous_response_id?: string
  total_messages: number
}



export function Navigation() {
  const pathname = usePathname()
  const { endpoint, refreshTrigger, loadConversation, currentConversationId, setCurrentConversationId, conversationDocs, addConversationDoc } = useChat()
  const [conversations, setConversations] = useState<ChatConversation[]>([])
  const [loadingConversations, setLoadingConversations] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  
  const handleNewConversation = () => {
    setCurrentConversationId(null)
    // The chat page will handle resetting messages when it detects a new conversation request
    window.dispatchEvent(new CustomEvent('newConversation'))
  }

  const handleFileUpload = async (file: File) => {
    console.log("Navigation file upload:", file.name)
    
    // Trigger loading start event for chat page
    window.dispatchEvent(new CustomEvent('fileUploadStart', { 
      detail: { filename: file.name } 
    }))
    
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('endpoint', endpoint)
      
      const response = await fetch('/api/upload_context', {
        method: 'POST',
        body: formData,
      })
      
      if (!response.ok) {
        const errorText = await response.text()
        console.error("Upload failed:", errorText)
        return
      }
      
      const result = await response.json()
      console.log("Upload result:", result)
      
      // Add the file to conversation docs
      if (result.filename) {
        addConversationDoc(result.filename)
      }
      
      // Trigger file upload event for chat page to handle
      window.dispatchEvent(new CustomEvent('fileUploaded', { 
        detail: { file, result } 
      }))
      
      // Trigger loading end event
      window.dispatchEvent(new CustomEvent('fileUploadComplete'))
      
    } catch (error) {
      console.error('Upload failed:', error)
      // Trigger loading end event even on error
      window.dispatchEvent(new CustomEvent('fileUploadComplete'))
      
      // Trigger error event for chat page to handle
      window.dispatchEvent(new CustomEvent('fileUploadError', { 
        detail: { filename: file.name, error: error instanceof Error ? error.message : 'Unknown error' } 
      }))
    }
  }

  const handleFilePickerClick = () => {
    fileInputRef.current?.click()
  }

  const handleFilePickerChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      handleFileUpload(files[0])
    }
    // Reset the input so the same file can be selected again
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const routes = [
    {
      label: "Chat",
      icon: MessageSquare,
      href: "/chat",
      active: pathname === "/" || pathname === "/chat",
    },
    {
      label: "Knowledge",
      icon: Library,
      href: "/knowledge",
      active: pathname === "/knowledge",
    },
    {
      label: "Settings",
      icon: Settings2,
      href: "/settings",
      active: pathname === "/settings",
    },
  ]

  const isOnChatPage = pathname === "/" || pathname === "/chat"

  // Fetch chat conversations when on chat page, endpoint changes, or refresh is triggered
  useEffect(() => {
    if (isOnChatPage) {
      fetchConversations()
    }
  }, [isOnChatPage, endpoint, refreshTrigger])

  const fetchConversations = async () => {
    setLoadingConversations(true)
    try {
      // Fetch from the selected endpoint only
      const apiEndpoint = endpoint === 'chat' ? '/api/chat/history' : '/api/langflow/history'
      
      const response = await fetch(apiEndpoint)
      if (response.ok) {
        const history = await response.json()
        const conversations = history.conversations || []
        
        // Sort conversations by last activity (most recent first)
        conversations.sort((a: ChatConversation, b: ChatConversation) => {
          const aTime = new Date(a.last_activity || a.created_at || 0).getTime()
          const bTime = new Date(b.last_activity || b.created_at || 0).getTime()
          return bTime - aTime
        })
        
        setConversations(conversations)
      } else {
        setConversations([])
      }
      
      // Conversation documents are now managed in chat context
      
    } catch (error) {
      console.error(`Failed to fetch ${endpoint} conversations:`, error)
      setConversations([])
    } finally {
      setLoadingConversations(false)
    }
  }

  return (
    <div className="space-y-4 py-4 flex flex-col h-full bg-background">
      <div className="px-3 py-2 flex-shrink-0">
        <div className="space-y-1">
          {routes.map((route) => (
            <div key={route.href}>
              <Link
                href={route.href}
                className={cn(
                  "text-sm group flex p-3 w-full justify-start font-medium cursor-pointer hover:bg-accent hover:text-accent-foreground rounded-lg transition-all",
                  route.active 
                    ? "bg-accent text-accent-foreground shadow-sm" 
                    : "text-foreground hover:text-accent-foreground",
                )}
              >
                <div className="flex items-center flex-1">
                  <route.icon className={cn("h-4 w-4 mr-3 shrink-0", route.active ? "text-accent-foreground" : "text-muted-foreground group-hover:text-foreground")} />
                  {route.label}
                </div>
              </Link>
              {route.label === "Settings" && (
                <div className="mx-3 my-2 border-t border-border/40" />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Chat Page Specific Sections */}
      {isOnChatPage && (
        <div className="flex-1 min-h-0 flex flex-col">
          {/* Conversations Section */}
          <div className="px-3 flex-shrink-0">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-muted-foreground">Conversations</h3>
              <button 
                className="p-1 hover:bg-accent rounded"
                onClick={handleNewConversation}
                title="Start new conversation"
              >
                <Plus className="h-4 w-4 text-muted-foreground" />
              </button>
            </div>
          </div>
          
          <div className="px-3 flex-1 min-h-0 flex flex-col">
            {/* Conversations List - grows naturally, doesn't fill all space */}
            <div className="flex-shrink-0 overflow-y-auto scrollbar-hide space-y-1 max-h-full">
              {loadingConversations ? (
                <div className="text-sm text-muted-foreground p-2">Loading...</div>
              ) : conversations.length === 0 ? (
                <div className="text-sm text-muted-foreground p-2">No conversations yet</div>
              ) : (
                conversations.map((conversation) => (
                  <div
                    key={conversation.response_id}
                    className={`p-2 rounded-lg hover:bg-accent cursor-pointer group ${
                      currentConversationId === conversation.response_id ? 'bg-accent' : ''
                    }`}
                    onClick={() => {
                      loadConversation(conversation)
                    }}
                  >
                    <div className="text-sm font-medium text-foreground mb-1 truncate">
                      {conversation.title}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {conversation.total_messages} messages
                    </div>
                    {conversation.last_activity && (
                      <div className="text-xs text-muted-foreground">
                        {new Date(conversation.last_activity).toLocaleDateString()}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>

            {/* Conversation Knowledge Section - appears right after last conversation */}
            <div className="flex-shrink-0 mt-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-muted-foreground">Conversation knowledge</h3>
                <button 
                  onClick={handleFilePickerClick}
                  className="p-1 hover:bg-accent rounded"
                >
                  <Plus className="h-4 w-4 text-muted-foreground" />
                </button>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleFilePickerChange}
                className="hidden"
                accept=".pdf,.doc,.docx,.txt,.md,.rtf,.odt"
              />
              <div className="overflow-y-auto scrollbar-hide space-y-1 max-h-40">
                {conversationDocs.length === 0 ? (
                  <div className="text-sm text-muted-foreground p-2">No documents yet</div>
                ) : (
                  conversationDocs.map((doc, index) => (
                    <div
                      key={index}
                      className="p-2 rounded-lg hover:bg-accent cursor-pointer group flex items-center"
                    >
                      <FileText className="h-4 w-4 mr-2 text-muted-foreground flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-foreground truncate">
                          {doc.filename}
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}