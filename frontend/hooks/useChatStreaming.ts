import { useRef, useState } from "react";
import type {
  FunctionCall,
  Message,
  TokenUsage,
} from "@/app/chat/_types/types";
import { useChat } from "@/contexts/chat-context";
import {
  detectImplicitToolCall,
  detectRAGFromContent,
  parseOpenAIChatChunk,
  parseOpenRAGChunk,
  parseRealtimeChunk,
} from "@/lib/chat-stream-parsers";
import type { FilterInput } from "@/lib/filter-normalization";
import { buildSearchPayloadFilters } from "@/lib/filter-normalization";

interface UseChatStreamingOptions {
  endpoint?: string;
  onComplete?: (message: Message, responseId: string | null) => void;
  onError?: (error: Error) => void;
}

interface SendMessageOptions {
  prompt: string;
  previousResponseId?: string;
  filters?: FilterInput;
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
        filters?: FilterInput;
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
        const payloadFilters = buildSearchPayloadFilters(filters);
        if (payloadFilters) {
          requestBody.filters = payloadFilters;
        }
      }

      if (filter_id) {
        requestBody.filter_id = filter_id;
      }

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
      const content = { value: "" };
      const currentFunctionCalls: FunctionCall[] = [];
      let newResponseId: string | null = null;
      let isError = false;
      const usage: { value: TokenUsage | undefined } = { value: undefined };

      if (!controller.signal.aborted && thisStreamId === streamIdRef.current) {
        setStreamingMessage({
          role: "assistant",
          content: "",
          timestamp: new Date(),
          isStreaming: true,
        });
      }

      try {
        streamLoop: while (true) {
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

                if (chunk.id) {
                  newResponseId = chunk.id;
                } else if (chunk.response_id) {
                  newResponseId = chunk.response_id;
                }

                parseOpenAIChatChunk(chunk, content, currentFunctionCalls) ||
                  parseRealtimeChunk(
                    chunk,
                    content,
                    currentFunctionCalls,
                    usage,
                  ) ||
                  parseOpenRAGChunk(chunk, content);
                detectImplicitToolCall(chunk, currentFunctionCalls);

                if (
                  chunk.finish_reason === "error" ||
                  chunk.status === "failed"
                ) {
                  console.error("Error detected in stream");
                  isError = true;
                  break streamLoop;
                }

                if (
                  !controller.signal.aborted &&
                  thisStreamId === streamIdRef.current
                ) {
                  setStreamingMessage({
                    role: "assistant",
                    content: content.value,
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

      if (
        !hasReceivedData ||
        (!content.value && currentFunctionCalls.length === 0)
      ) {
        throw new Error(
          "No response received from the server. Please try again.",
        );
      }

      if (currentFunctionCalls.length === 0 && content.value) {
        const ragCall = detectRAGFromContent(content.value);
        if (ragCall) currentFunctionCalls.push(ragCall);
      }

      const finalMessage: Message = {
        role: "assistant",
        content: content.value,
        functionCalls:
          currentFunctionCalls.length > 0 ? currentFunctionCalls : undefined,
        timestamp: new Date(),
        isStreaming: false,
        error: isError,
        usage: usage.value,
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
      const errorMessage = (error as Error).message;
      let errorContent = errorMessage; // Default to the actual error message

      // Only override with generic messages for specific infrastructure errors
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
      }
      // For all other errors (including Langflow errors), use the actual error message

      onError?.(error as Error);

      const errorMessageObj: Message = {
        role: "assistant",
        content: errorContent,
        timestamp: new Date(),
        isStreaming: false,
        error: true,
      };

      // Pass error message to onComplete so it gets added to chat history
      // This ensures errors appear immediately and persist on page refresh
      if (!streamAbortRef.current?.signal.aborted) {
        onComplete?.(errorMessageObj, null);
      }

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
