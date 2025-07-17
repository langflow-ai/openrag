"use client"

import { useState, useRef, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { MessageCircle, Send, Loader2, User, Bot } from "lucide-react"
import { cn } from "@/lib/utils"

interface Message {
  role: "user" | "assistant"
  content: string
  timestamp: Date
}

type EndpointType = "chat" | "langflow"

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [endpoint, setEndpoint] = useState<EndpointType>("chat")
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || loading) return

    const userMessage: Message = {
      role: "user",
      content: input.trim(),
      timestamp: new Date()
    }

    setMessages(prev => [...prev, userMessage])
    setInput("")
    setLoading(true)

    try {
      const apiEndpoint = endpoint === "chat" ? "/api/chat" : "/api/langflow"
      const response = await fetch(apiEndpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ prompt: userMessage.content }),
      })

      const result = await response.json()
      
      if (response.ok) {
        const assistantMessage: Message = {
          role: "assistant",
          content: result.response,
          timestamp: new Date()
        }
        setMessages(prev => [...prev, assistantMessage])
      } else {
        console.error("Chat failed:", result.error)
        const errorMessage: Message = {
          role: "assistant",
          content: "Sorry, I encountered an error. Please try again.",
          timestamp: new Date()
        }
        setMessages(prev => [...prev, errorMessage])
      }
    } catch (error) {
      console.error("Chat error:", error)
      const errorMessage: Message = {
        role: "assistant",
        content: "Sorry, I couldn't connect to the chat service. Please try again.",
        timestamp: new Date()
      }
      setMessages(prev => [...prev, errorMessage])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Chat Assistant</h1>
        <p className="text-muted-foreground mt-2">Ask questions about your documents and get AI-powered answers</p>
      </div>

      <Card className="h-[600px] flex flex-col max-w-full overflow-hidden">
        <CardHeader className="flex-shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <MessageCircle className="h-5 w-5" />
              <CardTitle>Chat</CardTitle>
            </div>
            <div className="flex items-center gap-2 bg-muted/50 rounded-lg p-1">
              <Button
                variant={endpoint === "chat" ? "default" : "ghost"}
                size="sm"
                onClick={() => setEndpoint("chat")}
                className="h-7 text-xs"
              >
                Chat
              </Button>
              <Button
                variant={endpoint === "langflow" ? "default" : "ghost"}
                size="sm"
                onClick={() => setEndpoint("langflow")}
                className="h-7 text-xs"
              >
                Langflow
              </Button>
            </div>
          </div>
          <CardDescription>
            Chat with AI about your indexed documents using {endpoint === "chat" ? "Chat" : "Langflow"} endpoint
          </CardDescription>
        </CardHeader>
        <CardContent className="flex-1 flex flex-col gap-4 min-h-0">
          {/* Messages Area */}
          <div className="flex-1 overflow-y-auto overflow-x-hidden space-y-6 p-4 rounded-lg bg-muted/20 min-h-0">
            {messages.length === 0 ? (
              <div className="flex items-center justify-center h-full text-muted-foreground">
                <div className="text-center">
                  <MessageCircle className="h-12 w-12 mx-auto mb-4 opacity-50" />
                  <p>Start a conversation by asking a question!</p>
                  <p className="text-sm mt-2">I can help you find information in your documents.</p>
                </div>
              </div>
            ) : (
              <>
                {messages.map((message, index) => (
                  <div key={index} className="space-y-2">
                    {message.role === "user" && (
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <div className="w-8 h-8 rounded-lg bg-primary/20 flex items-center justify-center">
                            <User className="h-4 w-4 text-primary" />
                          </div>
                          <span className="font-medium text-foreground">User</span>
                        </div>
                        <div className="pl-10 max-w-full">
                          <p className="text-foreground whitespace-pre-wrap break-words overflow-wrap-anywhere">{message.content}</p>
                        </div>
                      </div>
                    )}
                    
                    {message.role === "assistant" && (
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <div className="w-8 h-8 rounded-lg bg-accent/20 flex items-center justify-center">
                            <Bot className="h-4 w-4 text-accent-foreground" />
                          </div>
                          <span className="font-medium text-foreground">AI</span>
                          <span className="text-sm text-muted-foreground">gpt-4.1</span>
                        </div>
                        <div className="pl-10 max-w-full">
                          <div className="rounded-lg bg-card border border-border/40 p-4 max-w-full overflow-hidden">
                            <div className="flex items-center gap-2 mb-2">
                              <div className="w-2 h-2 bg-green-400 rounded-full"></div>
                              <span className="text-sm text-green-400 font-medium">Finished</span>
                              <span className="text-xs text-muted-foreground ml-auto">
                                {message.timestamp.toLocaleTimeString()}
                              </span>
                            </div>
                            <p className="text-foreground whitespace-pre-wrap break-words overflow-wrap-anywhere">{message.content}</p>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
                {loading && (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-lg bg-accent/20 flex items-center justify-center">
                        <Bot className="h-4 w-4 text-accent-foreground" />
                      </div>
                      <span className="font-medium text-foreground">AI</span>
                      <span className="text-sm text-muted-foreground">gpt-4.1</span>
                    </div>
                    <div className="pl-10 max-w-full">
                      <div className="rounded-lg bg-card border border-border/40 p-4 max-w-full overflow-hidden">
                        <div className="flex items-center gap-2 mb-2">
                          <Loader2 className="w-4 h-4 animate-spin text-white" />
                          <span className="text-sm text-white font-medium">Thinking...</span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </>
            )}
          </div>

          {/* Input Area */}
          <form onSubmit={handleSubmit} className="flex gap-2 flex-shrink-0 w-full">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question about your documents..."
              disabled={loading}
              className="flex-1 min-w-0"
            />
            <Button type="submit" disabled={!input.trim() || loading}>
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
} 