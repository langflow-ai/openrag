import { useRef, useState } from "react";
import type {
  FunctionCall,
  Message,
  SelectedFilters,
  TokenUsage,
} from "@/app/chat/_types/types";
import { useChat } from "@/contexts/chat-context";

interface UseChatStreamingOptions {
  endpoint?: string;
  onComplete?: (message: Message, responseId: string | null) => void;
  onError?: (error: Error) => void;
}

interface SendMessageOptions {
  prompt: string;
  previousResponseId?: string;
  filters?: SelectedFilters;
  filter_id?: string;
  limit?: number;
  scoreThreshold?: number;
}

export function useChatStreaming({
  endpoint = "/api/langflow",
  onComplete,
  onError,
}: UseChatStreamingOptions = {}) {
  const [streamingMessage, setStreamingMessage] = useState<Message | null>(
    null,
  );
  const [isLoading, setIsLoading] = useState(false);
  const streamAbortRef = useRef<AbortController | null>(null);
  const streamIdRef = useRef(0);

  const { refreshConversations } = useChat();

  const sendMessage = async ({
    prompt,
    previousResponseId,
    filters,
    filter_id,
    limit = 10,
    scoreThreshold = 0,
  }: SendMessageOptions) => {
    // Set up timeout to detect stuck/hanging requests
    let timeoutId: NodeJS.Timeout | null = null;
    let hasReceivedData = false;

    try {
      setIsLoading(true);

      // Abort any existing stream before starting a new one
      if (streamAbortRef.current) {
        streamAbortRef.current.abort();
      }

      const controller = new AbortController();
      streamAbortRef.current = controller;
      const thisStreamId = ++streamIdRef.current;

      // Set up timeout (60 seconds for initial response, then extended as data comes in)
      const startTimeout = () => {
        if (timeoutId) clearTimeout(timeoutId);
        timeoutId = setTimeout(() => {
          if (!hasReceivedData) {
            console.error("Chat request timed out - no response received");
            controller.abort();
            throw new Error("Request timed out. The server is not responding.");
          }
        }, 60000); // 60 second timeout
      };

      startTimeout();

      const requestBody: {
        prompt: string;
        stream: boolean;
        previous_response_id?: string;
        filters?: SelectedFilters;
        filter_id?: string;
        limit?: number;
        scoreThreshold?: number;
      } = {
        prompt,
        stream: true,
        limit,
        scoreThreshold,
      };

      if (previousResponseId) {
        requestBody.previous_response_id = previousResponseId;
      }

      if (filters) {
        requestBody.filters = filters;
      }

      if (filter_id) {
        requestBody.filter_id = filter_id;
      }

      console.log("[useChatStreaming] Sending request:", { filter_id, requestBody });

      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
        signal: controller.signal,
      });

      // Clear timeout once we get initial response
      if (timeoutId) clearTimeout(timeoutId);
      hasReceivedData = true;

      if (!response.ok) {
        const errorText = await response.text().catch(() => "Unknown error");
        throw new Error(`Server error (${response.status}): ${errorText}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("No reader available");
      }

      const decoder = new TextDecoder();
      let buffer = "";
      let currentContent = "";
      const currentFunctionCalls: FunctionCall[] = [];
      let newResponseId: string | null = null;
      let usageData: TokenUsage | undefined;

      // Initialize streaming message
      if (!controller.signal.aborted && thisStreamId === streamIdRef.current) {
        setStreamingMessage({
          role: "assistant",
          content: "",
          timestamp: new Date(),
          isStreaming: true,
        });
      }

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (controller.signal.aborted || thisStreamId !== streamIdRef.current)
            break;
          if (done) break;

          // Reset timeout on each chunk received
          hasReceivedData = true;
          if (timeoutId) clearTimeout(timeoutId);

          buffer += decoder.decode(value, { stream: true });

          // Process complete lines (JSON objects)
          const lines = buffer.split("\n");
          buffer = lines.pop() || ""; // Keep incomplete line in buffer

          for (const line of lines) {
            if (line.trim()) {
              try {
                const chunk = JSON.parse(line);
                
                // Investigation logging for Granite 3.3 8b tool call detection
                const chunkKeys = Object.keys(chunk);
                const toolRelatedKeys = chunkKeys.filter(key => 
                  key.toLowerCase().includes('tool') || 
                  key.toLowerCase().includes('call') || 
                  key.toLowerCase().includes('retrieval') ||
                  key.toLowerCase().includes('function') ||
                  key.toLowerCase().includes('result')
                );
                if (toolRelatedKeys.length > 0) {
                  console.log('[Tool Detection] Found tool-related keys:', toolRelatedKeys, chunk);
                }

                // Extract response ID if present
                if (chunk.id) {
                  newResponseId = chunk.id;
                } else if (chunk.response_id) {
                  newResponseId = chunk.response_id;
                }

                // Handle OpenAI Chat Completions streaming format
                if (chunk.object === "response.chunk" && chunk.delta) {
                  // Handle function calls in delta
                  if (chunk.delta.function_call) {
                    if (chunk.delta.function_call.name) {
                      const functionCall: FunctionCall = {
                        name: chunk.delta.function_call.name,
                        arguments: undefined,
                        status: "pending",
                        argumentsString:
                          chunk.delta.function_call.arguments || "",
                      };
                      currentFunctionCalls.push(functionCall);
                    } else if (chunk.delta.function_call.arguments) {
                      const lastFunctionCall =
                        currentFunctionCalls[currentFunctionCalls.length - 1];
                      if (lastFunctionCall) {
                        if (!lastFunctionCall.argumentsString) {
                          lastFunctionCall.argumentsString = "";
                        }
                        lastFunctionCall.argumentsString +=
                          chunk.delta.function_call.arguments;

                        if (lastFunctionCall.argumentsString.includes("}")) {
                          try {
                            const parsed = JSON.parse(
                              lastFunctionCall.argumentsString,
                            );
                            lastFunctionCall.arguments = parsed;
                            lastFunctionCall.status = "completed";
                          } catch (e) {
                            // Arguments not yet complete
                          }
                        }
                      }
                    }
                  }
                  // Handle tool calls in delta
                  else if (
                    chunk.delta.tool_calls &&
                    Array.isArray(chunk.delta.tool_calls)
                  ) {
                    for (const toolCall of chunk.delta.tool_calls) {
                      if (toolCall.function) {
                        if (toolCall.function.name) {
                          const functionCall: FunctionCall = {
                            name: toolCall.function.name,
                            arguments: undefined,
                            status: "pending",
                            argumentsString: toolCall.function.arguments || "",
                          };
                          currentFunctionCalls.push(functionCall);
                        } else if (toolCall.function.arguments) {
                          const lastFunctionCall =
                            currentFunctionCalls[
                              currentFunctionCalls.length - 1
                            ];
                          if (lastFunctionCall) {
                            if (!lastFunctionCall.argumentsString) {
                              lastFunctionCall.argumentsString = "";
                            }
                            lastFunctionCall.argumentsString +=
                              toolCall.function.arguments;

                            if (
                              lastFunctionCall.argumentsString.includes("}")
                            ) {
                              try {
                                const parsed = JSON.parse(
                                  lastFunctionCall.argumentsString,
                                );
                                lastFunctionCall.arguments = parsed;
                                lastFunctionCall.status = "completed";
                              } catch (e) {
                                // Arguments not yet complete
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                  // Handle content/text in delta
                  else if (chunk.delta.content) {
                    currentContent += chunk.delta.content;
                  }

                  // Handle finish reason
                  if (chunk.delta.finish_reason) {
                    currentFunctionCalls.forEach((fc) => {
                      if (fc.status === "pending" && fc.argumentsString) {
                        try {
                          fc.arguments = JSON.parse(fc.argumentsString);
                          fc.status = "completed";
                        } catch (e) {
                          fc.arguments = { raw: fc.argumentsString };
                          fc.status = "error";
                        }
                      }
                    });
                  }
                }
                // Handle Realtime API format - function call added
                else if (
                  chunk.type === "response.output_item.added" &&
                  chunk.item?.type === "function_call"
                ) {
                  let existing = currentFunctionCalls.find(
                    (fc) => fc.id === chunk.item.id,
                  );
                  if (!existing) {
                    existing = [...currentFunctionCalls]
                      .reverse()
                      .find(
                        (fc) =>
                          fc.status === "pending" &&
                          !fc.id &&
                          fc.name === (chunk.item.tool_name || chunk.item.name),
                      );
                  }

                  if (existing) {
                    existing.id = chunk.item.id;
                    existing.type = chunk.item.type;
                    existing.name =
                      chunk.item.tool_name || chunk.item.name || existing.name;
                    existing.arguments =
                      chunk.item.inputs || existing.arguments;
                  } else {
                    const functionCall: FunctionCall = {
                      name:
                        chunk.item.tool_name || chunk.item.name || "unknown",
                      arguments: chunk.item.inputs || undefined,
                      status: "pending",
                      argumentsString: "",
                      id: chunk.item.id,
                      type: chunk.item.type,
                    };
                    currentFunctionCalls.push(functionCall);
                  }
                }
                // Handle Realtime API format - tool call added
                else if (
                  chunk.type === "response.output_item.added" &&
                  chunk.item?.type?.includes("_call") &&
                  chunk.item?.type !== "function_call"
                ) {
                  let existing = currentFunctionCalls.find(
                    (fc) => fc.id === chunk.item.id,
                  );
                  if (!existing) {
                    existing = [...currentFunctionCalls]
                      .reverse()
                      .find(
                        (fc) =>
                          fc.status === "pending" &&
                          !fc.id &&
                          fc.name ===
                            (chunk.item.tool_name ||
                              chunk.item.name ||
                              chunk.item.type),
                      );
                  }

                  if (existing) {
                    existing.id = chunk.item.id;
                    existing.type = chunk.item.type;
                    existing.name =
                      chunk.item.tool_name ||
                      chunk.item.name ||
                      chunk.item.type ||
                      existing.name;
                    existing.arguments =
                      chunk.item.inputs || existing.arguments;
                  } else {
                    const functionCall = {
                      name:
                        chunk.item.tool_name ||
                        chunk.item.name ||
                        chunk.item.type ||
                        "unknown",
                      arguments: chunk.item.inputs || {},
                      status: "pending" as const,
                      id: chunk.item.id,
                      type: chunk.item.type,
                    };
                    currentFunctionCalls.push(functionCall);
                  }
                }
                // Handle function call done
                else if (
                  chunk.type === "response.output_item.done" &&
                  chunk.item?.type === "function_call"
                ) {
                  const functionCall = currentFunctionCalls.find(
                    (fc) =>
                      fc.id === chunk.item.id ||
                      fc.name === chunk.item.tool_name ||
                      fc.name === chunk.item.name,
                  );

                  if (functionCall) {
                    functionCall.status =
                      chunk.item.status === "completed" ? "completed" : "error";
                    functionCall.id = chunk.item.id;
                    functionCall.type = chunk.item.type;
                    functionCall.name =
                      chunk.item.tool_name ||
                      chunk.item.name ||
                      functionCall.name;
                    functionCall.arguments =
                      chunk.item.inputs || functionCall.arguments;

                    if (chunk.item.results) {
                      functionCall.result = chunk.item.results;
                    }
                  }
                }
                // Handle tool call done with results
                else if (
                  chunk.type === "response.output_item.done" &&
                  chunk.item?.type?.includes("_call") &&
                  chunk.item?.type !== "function_call"
                ) {
                  const functionCall = currentFunctionCalls.find(
                    (fc) =>
                      fc.id === chunk.item.id ||
                      fc.name === chunk.item.tool_name ||
                      fc.name === chunk.item.name ||
                      fc.name === chunk.item.type ||
                      fc.name.includes(chunk.item.type.replace("_call", "")) ||
                      chunk.item.type.includes(fc.name),
                  );

                  if (functionCall) {
                    functionCall.arguments =
                      chunk.item.inputs || functionCall.arguments;
                    functionCall.status =
                      chunk.item.status === "completed" ? "completed" : "error";
                    functionCall.id = chunk.item.id;
                    functionCall.type = chunk.item.type;

                    if (chunk.item.results) {
                      functionCall.result = chunk.item.results;
                    }
                  } else {
                    const newFunctionCall = {
                      name:
                        chunk.item.tool_name ||
                        chunk.item.name ||
                        chunk.item.type ||
                        "unknown",
                      arguments: chunk.item.inputs || {},
                      status: "completed" as const,
                      id: chunk.item.id,
                      type: chunk.item.type,
                      result: chunk.item.results,
                    };
                    currentFunctionCalls.push(newFunctionCall);
                  }
                }
                // Handle text output streaming (Realtime API)
                else if (chunk.type === "response.output_text.delta") {
                  currentContent += chunk.delta || "";
                }
                // Handle response.completed event - capture usage
                else if (chunk.type === "response.completed" && chunk.response?.usage) {
                  usageData = chunk.response.usage;
                }
                // Handle OpenRAG backend format
                else if (chunk.output_text) {
                  currentContent += chunk.output_text;
                } else if (chunk.delta) {
                  if (typeof chunk.delta === "string") {
                    currentContent += chunk.delta;
                  } else if (typeof chunk.delta === "object") {
                    if (chunk.delta.content) {
                      currentContent += chunk.delta.content;
                    } else if (chunk.delta.text) {
                      currentContent += chunk.delta.text;
                    }
                  }
                }
                
                // Heuristic detection for implicit tool calls (Granite 3.3 8b workaround)
                // Check if chunk contains retrieval results without explicit tool call markers
                const hasImplicitToolCall = (
                  // Check for various result indicators in the chunk
                  (chunk.results && Array.isArray(chunk.results) && chunk.results.length > 0) ||
                  (chunk.outputs && Array.isArray(chunk.outputs) && chunk.outputs.length > 0) ||
                  // Check for retrieval-related fields
                  chunk.retrieved_documents ||
                  chunk.retrieval_results ||
                  // Check for nested data structures that might contain results
                  (chunk.data && typeof chunk.data === 'object' && (
                    chunk.data.results || 
                    chunk.data.retrieved_documents ||
                    chunk.data.retrieval_results
                  ))
                );
                
                if (hasImplicitToolCall && currentFunctionCalls.length === 0) {
                  console.log('[Heuristic Detection] Detected implicit tool call:', chunk);
                  
                  // Create a synthetic function call for the UI
                  const results = chunk.results || chunk.outputs || chunk.retrieved_documents || 
                                 chunk.retrieval_results || chunk.data?.results || 
                                 chunk.data?.retrieved_documents || [];
                  
                  const syntheticFunctionCall: FunctionCall = {
                    name: "Retrieval",
                    arguments: { implicit: true, detected_heuristically: true },
                    status: "completed",
                    type: "retrieval_call",
                    result: results,
                  };
                  currentFunctionCalls.push(syntheticFunctionCall);
                  console.log('[Heuristic Detection] Created synthetic function call');
                }

                // Update streaming message in real-time
                if (
                  !controller.signal.aborted &&
                  thisStreamId === streamIdRef.current
                ) {
                  setStreamingMessage({
                    role: "assistant",
                    content: currentContent,
                    functionCalls:
                      currentFunctionCalls.length > 0
                        ? [...currentFunctionCalls]
                        : undefined,
                    timestamp: new Date(),
                    isStreaming: true,
                  });
                }
              } catch (parseError) {
                console.warn("Failed to parse chunk:", line, parseError);
              }
            }
          }
        }
      } finally {
        reader.releaseLock();
        if (timeoutId) clearTimeout(timeoutId);
      }

      // Check if we got any content at all
      if (
        !hasReceivedData ||
        (!currentContent && currentFunctionCalls.length === 0)
      ) {
        throw new Error(
          "No response received from the server. Please try again.",
        );
      }
      
      // Post-processing: Heuristic detection based on final content
      // If no explicit tool calls detected but content shows RAG indicators
      if (currentFunctionCalls.length === 0 && currentContent) {
        // Check for citation patterns that indicate RAG usage
        const hasCitations = /\(Source:|\[Source:|\bSource:|filename:|document:/i.test(currentContent);
        // Check for common RAG response patterns
        const hasRAGPattern = /based on.*(?:document|file|information|data)|according to.*(?:document|file)/i.test(currentContent);
        
        if (hasCitations || hasRAGPattern) {
          console.log('[Post-Processing] Detected RAG usage from content patterns');
          const syntheticFunctionCall: FunctionCall = {
            name: "Retrieval",
            arguments: { 
              implicit: true, 
              detected_from: hasCitations ? "citations" : "content_patterns"
            },
            status: "completed",
            type: "retrieval_call",
          };
          currentFunctionCalls.push(syntheticFunctionCall);
        }
      }

      // Finalize the message
      const finalMessage: Message = {
        role: "assistant",
        content: currentContent,
        functionCalls:
          currentFunctionCalls.length > 0 ? currentFunctionCalls : undefined,
        timestamp: new Date(),
        isStreaming: false,
        usage: usageData,
      };

      if (!controller.signal.aborted && thisStreamId === streamIdRef.current) {
        // Clear streaming message and call onComplete with final message
        setStreamingMessage(null);
        onComplete?.(finalMessage, newResponseId);
        refreshConversations(true);
        return finalMessage;
      }

      return null;
    } catch (error) {
      // Clean up timeout
      if (timeoutId) clearTimeout(timeoutId);

      // If stream was aborted by user, don't handle as error
      if (
        streamAbortRef.current?.signal.aborted &&
        !(error as Error).message?.includes("timed out")
      ) {
        return null;
      }

      console.error("Chat stream error:", error);
      setStreamingMessage(null);

      // Create user-friendly error message
      let errorContent =
        "Sorry, I couldn't connect to the chat service. Please try again.";

      const errorMessage = (error as Error).message;
      if (errorMessage?.includes("timed out")) {
        errorContent =
          "The request timed out. The server took too long to respond. Please try again.";
      } else if (errorMessage?.includes("No response")) {
        errorContent = "The server didn't return a response. Please try again.";
      } else if (
        errorMessage?.includes("NetworkError") ||
        errorMessage?.includes("Failed to fetch")
      ) {
        errorContent =
          "Network error. Please check your connection and try again.";
      } else if (errorMessage?.includes("Server error")) {
        errorContent = errorMessage; // Use the detailed server error message
      }

      onError?.(error as Error);

      const errorMessageObj: Message = {
        role: "assistant",
        content: errorContent,
        timestamp: new Date(),
        isStreaming: false,
      };

      return errorMessageObj;
    } finally {
      if (timeoutId) clearTimeout(timeoutId);
      setIsLoading(false);
    }
  };

  const abortStream = () => {
    if (streamAbortRef.current) {
      streamAbortRef.current.abort();
    }
    setStreamingMessage(null);
    setIsLoading(false);
  };

  return {
    streamingMessage,
    isLoading,
    sendMessage,
    abortStream,
  };
}
