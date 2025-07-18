"use client"

import { useState, useRef, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { MessageCircle, Send, Loader2, User, Bot, Zap, Settings, ChevronDown, ChevronRight } from "lucide-react"

interface Message {
  role: "user" | "assistant"
  content: string
  timestamp: Date
  functionCalls?: FunctionCall[]
  isStreaming?: boolean
}

interface FunctionCall {
  name: string
  arguments?: Record<string, unknown>
  result?: Record<string, unknown>
  status: "pending" | "completed" | "error"
  argumentsString?: string
}

type EndpointType = "chat" | "langflow"

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [endpoint, setEndpoint] = useState<EndpointType>("chat")
  const [asyncMode, setAsyncMode] = useState(false)
  const [streamingMessage, setStreamingMessage] = useState<{
    content: string
    functionCalls: FunctionCall[]
    timestamp: Date
  } | null>(null)
  const [expandedFunctionCalls, setExpandedFunctionCalls] = useState<Set<string>>(new Set())
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, streamingMessage])

  const handleSSEStream = async (userMessage: Message) => {
    const apiEndpoint = endpoint === "chat" ? "/api/chat" : "/api/langflow"
    
    try {
      const response = await fetch(apiEndpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ 
          prompt: userMessage.content,
          stream: true 
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error("No reader available")
      }

      const decoder = new TextDecoder()
      let buffer = ""
      let currentContent = ""
      const currentFunctionCalls: FunctionCall[] = []
      
      // Initialize streaming message
      setStreamingMessage({
        content: "",
        functionCalls: [],
        timestamp: new Date()
      })

      try {
        while (true) {
          const { done, value } = await reader.read()
          
          if (done) break
          
          buffer += decoder.decode(value, { stream: true })
          
          // Process complete lines (JSON objects)
          const lines = buffer.split('\n')
          buffer = lines.pop() || "" // Keep incomplete line in buffer
          
          for (const line of lines) {
            if (line.trim()) {
              try {
                const chunk = JSON.parse(line)
                console.log("Received chunk:", chunk.type || chunk.object, chunk)
                
                // Handle OpenAI Chat Completions streaming format
                if (chunk.object === "response.chunk" && chunk.delta) {
                  // Handle function calls in delta
                  if (chunk.delta.function_call) {
                    console.log("Function call in delta:", chunk.delta.function_call)
                    
                    // Check if this is a new function call
                    if (chunk.delta.function_call.name) {
                      console.log("New function call:", chunk.delta.function_call.name)
                      const functionCall: FunctionCall = {
                        name: chunk.delta.function_call.name,
                        arguments: undefined,
                        status: "pending",
                        argumentsString: chunk.delta.function_call.arguments || ""
                      }
                      currentFunctionCalls.push(functionCall)
                      console.log("Added function call:", functionCall)
                    }
                    // Or if this is arguments continuation
                    else if (chunk.delta.function_call.arguments) {
                      console.log("Function call arguments delta:", chunk.delta.function_call.arguments)
                      const lastFunctionCall = currentFunctionCalls[currentFunctionCalls.length - 1]
                      if (lastFunctionCall) {
                        if (!lastFunctionCall.argumentsString) {
                          lastFunctionCall.argumentsString = ""
                        }
                        lastFunctionCall.argumentsString += chunk.delta.function_call.arguments
                        console.log("Accumulated arguments:", lastFunctionCall.argumentsString)
                        
                        // Try to parse arguments if they look complete
                        if (lastFunctionCall.argumentsString.includes("}")) {
                          try {
                            const parsed = JSON.parse(lastFunctionCall.argumentsString)
                            lastFunctionCall.arguments = parsed
                            lastFunctionCall.status = "completed"
                            console.log("Parsed function arguments:", parsed)
                          } catch (e) {
                            console.log("Arguments not yet complete or invalid JSON:", e)
                          }
                        }
                      }
                    }
                  }
                  
                  // Handle tool calls in delta  
                  else if (chunk.delta.tool_calls && Array.isArray(chunk.delta.tool_calls)) {
                    console.log("Tool calls in delta:", chunk.delta.tool_calls)
                    
                    for (const toolCall of chunk.delta.tool_calls) {
                      if (toolCall.function) {
                        // Check if this is a new tool call
                        if (toolCall.function.name) {
                          console.log("New tool call:", toolCall.function.name)
                          const functionCall: FunctionCall = {
                            name: toolCall.function.name,
                            arguments: undefined,
                            status: "pending",
                            argumentsString: toolCall.function.arguments || ""
                          }
                          currentFunctionCalls.push(functionCall)
                          console.log("Added tool call:", functionCall)
                        }
                        // Or if this is arguments continuation
                        else if (toolCall.function.arguments) {
                          console.log("Tool call arguments delta:", toolCall.function.arguments)
                          const lastFunctionCall = currentFunctionCalls[currentFunctionCalls.length - 1]
                          if (lastFunctionCall) {
                            if (!lastFunctionCall.argumentsString) {
                              lastFunctionCall.argumentsString = ""
                            }
                            lastFunctionCall.argumentsString += toolCall.function.arguments
                            console.log("Accumulated tool arguments:", lastFunctionCall.argumentsString)
                            
                            // Try to parse arguments if they look complete
                            if (lastFunctionCall.argumentsString.includes("}")) {
                              try {
                                const parsed = JSON.parse(lastFunctionCall.argumentsString)
                                lastFunctionCall.arguments = parsed
                                lastFunctionCall.status = "completed"
                                console.log("Parsed tool arguments:", parsed)
                              } catch (e) {
                                console.log("Tool arguments not yet complete or invalid JSON:", e)
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                  
                  // Handle content/text in delta
                  else if (chunk.delta.content) {
                    console.log("Content delta:", chunk.delta.content)
                    currentContent += chunk.delta.content
                  }
                  
                  // Handle finish reason
                  if (chunk.delta.finish_reason) {
                    console.log("Finish reason:", chunk.delta.finish_reason)
                    // Mark any pending function calls as completed
                    currentFunctionCalls.forEach(fc => {
                      if (fc.status === "pending" && fc.argumentsString) {
                        try {
                          fc.arguments = JSON.parse(fc.argumentsString)
                          fc.status = "completed"
                          console.log("Completed function call on finish:", fc)
                        } catch (e) {
                          fc.arguments = { raw: fc.argumentsString }
                          fc.status = "error"
                          console.log("Error parsing function call on finish:", fc, e)
                        }
                      }
                    })
                  }
                }
                
                // Handle Realtime API format (this is what you're actually getting!)
                else if (chunk.type === "response.output_item.added" && chunk.item?.type === "function_call") {
                  console.log("Function call started (Realtime API):", chunk.item.name)
                  const functionCall: FunctionCall = {
                    name: chunk.item.name || "unknown",
                    arguments: undefined,
                    status: "pending",
                    argumentsString: ""
                  }
                  currentFunctionCalls.push(functionCall)
                }
                
                // Handle function call arguments streaming (Realtime API)
                else if (chunk.type === "response.function_call_arguments.delta") {
                  console.log("Function args delta (Realtime API):", chunk.delta)
                  const lastFunctionCall = currentFunctionCalls[currentFunctionCalls.length - 1]
                  if (lastFunctionCall) {
                    if (!lastFunctionCall.argumentsString) {
                      lastFunctionCall.argumentsString = ""
                    }
                    lastFunctionCall.argumentsString += chunk.delta || ""
                    console.log("Accumulated arguments (Realtime API):", lastFunctionCall.argumentsString)
                  }
                }
                
                // Handle function call arguments completion (Realtime API)
                else if (chunk.type === "response.function_call_arguments.done") {
                  console.log("Function args done (Realtime API):", chunk.arguments)
                  const lastFunctionCall = currentFunctionCalls[currentFunctionCalls.length - 1]
                  if (lastFunctionCall) {
                    try {
                      lastFunctionCall.arguments = JSON.parse(chunk.arguments || "{}")
                      lastFunctionCall.status = "completed"
                      console.log("Parsed function arguments (Realtime API):", lastFunctionCall.arguments)
                    } catch (e) {
                      lastFunctionCall.arguments = { raw: chunk.arguments }
                      lastFunctionCall.status = "error"
                      console.log("Error parsing function arguments (Realtime API):", e)
                    }
                  }
                }
                
                // Handle function call completion (Realtime API)
                else if (chunk.type === "response.output_item.done" && chunk.item?.type === "function_call") {
                  console.log("Function call done (Realtime API):", chunk.item.status)
                  const lastFunctionCall = currentFunctionCalls[currentFunctionCalls.length - 1]
                  if (lastFunctionCall) {
                    lastFunctionCall.status = chunk.item.status === "completed" ? "completed" : "error"
                  }
                }
                
                // Handle function call results
                else if (chunk.type === "response.function_call.result" || chunk.type === "function_call_result") {
                  console.log("Function call result:", chunk.result || chunk)
                  const lastFunctionCall = currentFunctionCalls[currentFunctionCalls.length - 1]
                  if (lastFunctionCall) {
                    lastFunctionCall.result = chunk.result || chunk.output || chunk.response
                    lastFunctionCall.status = "completed"
                  }
                }
                
                // Handle tool call results  
                else if (chunk.type === "response.tool_call.result" || chunk.type === "tool_call_result") {
                  console.log("Tool call result:", chunk.result || chunk)
                  const lastFunctionCall = currentFunctionCalls[currentFunctionCalls.length - 1]
                  if (lastFunctionCall) {
                    lastFunctionCall.result = chunk.result || chunk.output || chunk.response
                    lastFunctionCall.status = "completed" 
                  }
                }
                
                // Handle generic results that might be in different formats
                else if ((chunk.type && chunk.type.includes("result")) || chunk.result) {
                  console.log("Generic result:", chunk)
                  const lastFunctionCall = currentFunctionCalls[currentFunctionCalls.length - 1]
                  if (lastFunctionCall && !lastFunctionCall.result) {
                    lastFunctionCall.result = chunk.result || chunk.output || chunk.response || chunk
                    lastFunctionCall.status = "completed"
                  }
                }
                
                // Handle text output streaming (Realtime API)
                else if (chunk.type === "response.output_text.delta") {
                  console.log("Text delta (Realtime API):", chunk.delta)
                  currentContent += chunk.delta || ""
                }
                
                // Log unhandled chunks
                else if (chunk.type !== null && chunk.object !== "response.chunk") {
                  console.log("Unhandled chunk format:", chunk)
                }
                
                // Update streaming message
                setStreamingMessage({
                  content: currentContent,
                  functionCalls: [...currentFunctionCalls],
                  timestamp: new Date()
                })
                
              } catch (parseError) {
                console.warn("Failed to parse chunk:", line, parseError)
              }
            }
          }
        }
      } finally {
        reader.releaseLock()
      }

      // Finalize the message
      const finalMessage: Message = {
        role: "assistant",
        content: currentContent,
        functionCalls: currentFunctionCalls,
        timestamp: new Date()
      }
      
      setMessages(prev => [...prev, finalMessage])
      setStreamingMessage(null)
      
    } catch (error) {
      console.error("SSE Stream error:", error)
      setStreamingMessage(null)
      
      const errorMessage: Message = {
        role: "assistant",
        content: "Sorry, I couldn't connect to the chat service. Please try again.",
        timestamp: new Date()
      }
      setMessages(prev => [...prev, errorMessage])
    }
  }

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

    if (asyncMode) {
      await handleSSEStream(userMessage)
    } else {
      // Original non-streaming logic
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
      }
    }
    
    setLoading(false)
  }

  const toggleFunctionCall = (functionCallId: string) => {
    setExpandedFunctionCalls(prev => {
      const newSet = new Set(prev)
      if (newSet.has(functionCallId)) {
        newSet.delete(functionCallId)
      } else {
        newSet.add(functionCallId)
      }
      return newSet
    })
  }

  const renderFunctionCalls = (functionCalls: FunctionCall[], messageIndex?: number) => {
    if (!functionCalls || functionCalls.length === 0) return null
    
    return (
      <div className="mb-3 space-y-2">
        {functionCalls.map((fc, index) => {
          const functionCallId = `${messageIndex || 'streaming'}-${index}`
          const isExpanded = expandedFunctionCalls.has(functionCallId)
          
          return (
            <div key={index} className="rounded-lg bg-blue-500/10 border border-blue-500/20 p-3">
              <div 
                className="flex items-center gap-2 cursor-pointer hover:bg-blue-500/5 -m-3 p-3 rounded-lg transition-colors"
                onClick={() => toggleFunctionCall(functionCallId)}
              >
                <Settings className="h-4 w-4 text-blue-400" />
                <span className="text-sm font-medium text-blue-400 flex-1">
                  Function Call: {fc.name}
                </span>
                <div className={`px-2 py-1 rounded text-xs font-medium ${
                  fc.status === "completed" ? "bg-green-500/20 text-green-400" :
                  fc.status === "error" ? "bg-red-500/20 text-red-400" :
                  "bg-yellow-500/20 text-yellow-400"
                }`}>
                  {fc.status}
                </div>
                {isExpanded ? (
                  <ChevronDown className="h-4 w-4 text-blue-400" />
                ) : (
                  <ChevronRight className="h-4 w-4 text-blue-400" />
                )}
              </div>
              
              {isExpanded && (
                <div className="mt-3 pt-3 border-t border-blue-500/20">
                  {/* Show arguments - either completed or streaming */}
                  {(fc.arguments || fc.argumentsString) && (
                    <div className="text-xs text-muted-foreground mb-3">
                      <span className="font-medium">Arguments:</span>
                      <pre className="mt-1 p-2 bg-muted/30 rounded text-xs overflow-x-auto">
                        {fc.arguments 
                          ? JSON.stringify(fc.arguments, null, 2)
                          : fc.argumentsString || "..."
                        }
                      </pre>
                    </div>
                  )}
                  
                  {fc.result && (
                    <div className="text-xs text-muted-foreground">
                      <span className="font-medium">Result:</span>
                      <pre className="mt-1 p-2 bg-muted/30 rounded text-xs overflow-x-auto">
                        {JSON.stringify(fc.result, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    )
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
            <div className="flex items-center gap-4">
              {/* Async Mode Toggle */}
              <div className="flex items-center gap-2 bg-muted/50 rounded-lg p-1">
                <Button
                  variant={!asyncMode ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setAsyncMode(false)}
                  className="h-7 text-xs"
                >
                  Sync
                </Button>
                <Button
                  variant={asyncMode ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setAsyncMode(true)}
                  className="h-7 text-xs"
                >
                  <Zap className="h-3 w-3 mr-1" />
                  Async
                </Button>
              </div>
              {/* Endpoint Toggle */}
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
          </div>
          <CardDescription>
            Chat with AI about your indexed documents using {endpoint === "chat" ? "Chat" : "Langflow"} endpoint 
            {asyncMode ? " with real-time streaming" : ""}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex-1 flex flex-col gap-4 min-h-0">
          {/* Messages Area */}
          <div className="flex-1 overflow-y-auto overflow-x-hidden space-y-6 p-4 rounded-lg bg-muted/20 min-h-0">
            {messages.length === 0 && !streamingMessage ? (
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
                            {renderFunctionCalls(message.functionCalls || [], index)}
                            <p className="text-foreground whitespace-pre-wrap break-words overflow-wrap-anywhere">{message.content}</p>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
                
                {/* Streaming Message Display */}
                {streamingMessage && (
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
                          <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
                          <span className="text-sm text-blue-400 font-medium">Streaming...</span>
                          <span className="text-xs text-muted-foreground ml-auto">
                            {streamingMessage.timestamp.toLocaleTimeString()}
                          </span>
                        </div>
                        {renderFunctionCalls(streamingMessage.functionCalls, messages.length)}
                        <p className="text-foreground whitespace-pre-wrap break-words overflow-wrap-anywhere">
                          {streamingMessage.content}
                          <span className="inline-block w-2 h-4 bg-blue-400 ml-1 animate-pulse"></span>
                        </p>
                      </div>
                    </div>
                  </div>
                )}
                
                {loading && !asyncMode && (
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