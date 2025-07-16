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

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
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
      const response = await fetch("/api/chat", {
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
    <div className="max-w-4xl mx-auto space-y-8">
      <div className="text-center">
        <h1 className="text-3xl font-bold tracking-tight">Chat Assistant</h1>
        <p className="text-muted-foreground mt-2">Ask questions about your documents and get AI-powered answers</p>
      </div>

      <Card className="h-[600px] flex flex-col">
        <CardHeader className="flex-shrink-0">
          <CardTitle className="flex items-center gap-2">
            <MessageCircle className="h-5 w-5" />
            Chat
          </CardTitle>
          <CardDescription>
            Chat with AI about your indexed documents
          </CardDescription>
        </CardHeader>
        <CardContent className="flex-1 flex flex-col gap-4 min-h-0">
          {/* Messages Area */}
          <div className="flex-1 overflow-y-auto overflow-x-hidden space-y-4 p-4 rounded-lg bg-muted/20 min-h-0">
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
                  <div
                    key={index}
                    className={cn(
                      "flex w-full",
                      message.role === "user" ? "justify-end" : "justify-start"
                    )}
                  >
                    <div
                      className={cn(
                        "flex items-start gap-3 max-w-[80%] min-w-0",
                        message.role === "user" ? "flex-row-reverse" : "flex-row"
                      )}
                    >
                      <div
                        className={cn(
                          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                          message.role === "user"
                            ? "bg-primary text-primary-foreground"
                            : "bg-secondary text-secondary-foreground"
                        )}
                      >
                        {message.role === "user" ? (
                          <User className="h-4 w-4" />
                        ) : (
                          <Bot className="h-4 w-4" />
                        )}
                      </div>
                      <div
                        className={cn(
                          "rounded-lg px-3 py-2 text-sm min-w-0 overflow-hidden",
                          message.role === "user"
                            ? "bg-primary text-primary-foreground"
                            : "bg-card border border-border/40"
                        )}
                      >
                        <p className="whitespace-pre-wrap break-words overflow-wrap-anywhere">{message.content}</p>
                        <p className="text-xs opacity-70 mt-1">
                          {message.timestamp.toLocaleTimeString()}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
                {loading && (
                  <div className="flex w-full justify-start">
                    <div className="flex items-start gap-3 max-w-[80%] min-w-0">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary text-secondary-foreground">
                        <Bot className="h-4 w-4" />
                      </div>
                      <div className="rounded-lg px-3 py-2 text-sm bg-card border border-border/40 min-w-0 overflow-hidden">
                        <div className="flex items-center gap-2">
                          <Loader2 className="h-4 w-4 animate-spin" />
                          <span>Thinking...</span>
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
          <form onSubmit={handleSubmit} className="flex gap-2 flex-shrink-0">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question about your documents..."
              disabled={loading}
              className="flex-1"
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