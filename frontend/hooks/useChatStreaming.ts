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

// How long the stream may go without producing output before it is treated as
// dead. Applies to the wait for the first chunk and to every gap after it.
const STREAM_STALL_TIMEOUT_MS = 60000;

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
    let stalled = false;

    try {
      setIsLoading(true);

      // Abort any existing stream before starting a new one
      if (streamAbortRef.current) {
        streamAbortRef.current.abort();
      }

      const controller = new AbortController();
      streamAbortRef.current = controller;
      const thisStreamId = ++streamIdRef.current;

      // Stall guard: armed before the request and re-armed on every chunk that
      // carries actual output. An open stream that stops producing (a provider
      // emitting only keepalives, for instance) would otherwise leave the UI
      // "Thinking..." forever, since there is no error and no data to render.
      // Aborting here surfaces a timeout through onError instead.
      const armStallTimeout = () => {
        if (timeoutId) clearTimeout(timeoutId);
        timeoutId = setTimeout(() => {
          console.error("Chat request timed out - no data received");
          stalled = true;
          controller.abort();
        }, STREAM_STALL_TIMEOUT_MS);
      };

      armStallTimeout();

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

      console.log("[useChatStreaming] Sending request:", {
        filter_id,
        requestBody,
      });

      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
        signal: controller.signal,
      });

      // Response headers alone are not data — leave the stall guard armed until
      // the body actually produces something.
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

          buffer += decoder.decode(value, { stream: true });

          // Process complete lines (JSON objects)
          const lines = buffer.split("\n");
          buffer = lines.pop() || ""; // Keep incomplete line in buffer
          let progressed = false;

          for (const line of lines) {
            if (line.trim()) {
              try {
                const chunk = JSON.parse(line);

                // Keepalives hold the connection open without producing output,
                // so they must not count as progress — otherwise a provider that
                // only sends them resets the stall guard forever.
                if (chunk?.type !== "keepalive") {
                  progressed = true;
                }

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

          if (progressed) {
            hasReceivedData = true;
            armStallTimeout();
          }
        }
      } finally {
        reader.releaseLock();
        if (timeoutId) clearTimeout(timeoutId);
      }

      // The stall guard aborts the reader, which breaks the loop rather than
      // raising. Raise here so a stall that arrives mid-answer is reported too,
      // instead of returning null and leaving the caller's spinner running.
      if (stalled) {
        throw new Error("Request timed out. The server stopped sending data.");
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

      // A stall aborts the same controller a user cancel does, so translate it
      // first — otherwise it takes the silent cancel path below and the caller
      // never learns the request died.
      const streamError = stalled
        ? new Error("Request timed out. The server stopped sending data.")
        : (error as Error);

      // If stream was aborted by user, don't handle as error
      if (
        !stalled &&
        streamAbortRef.current?.signal.aborted &&
        !streamError.message?.includes("timed out")
      ) {
        return null;
      }

      console.error("Chat stream error:", streamError);
      setStreamingMessage(null);

      // Create user-friendly error message
      const errorMessage = streamError.message;
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

      onError?.(streamError);

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
