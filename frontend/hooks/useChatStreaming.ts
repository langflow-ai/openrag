import { useRef, useState } from "react";
import type {
  FunctionCall,
  Message,
  TokenUsage,
} from "@/app/chat/_types/types";
import { useChat } from "@/contexts/chat-context";
import {
  extractStreamProviderError,
  formatProviderErrorMessage,
  looksLikeProviderErrorContent,
} from "@/lib/chat-stream-errors";
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
  /** OpenRAG sidebar thread id (kept after errors; distinct from Langflow session). */
  conversationId?: string;
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
    conversationId,
    filters,
    filter_id,
    limit = 10,
    scoreThreshold = 0,
  }: SendMessageOptions) => {
    // Set up timeout to detect stuck/hanging requests
    let timeoutId: NodeJS.Timeout | null = null;
    let hasReceivedData = false;
    // Hoisted so the catch path can still attach a failed turn to history.
    let newResponseId: string | null = null;

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
        conversation_id?: string;
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

      if (conversationId) {
        requestBody.conversation_id = conversationId;
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
      const usage: { value: TokenUsage | undefined } = { value: undefined };
      let providerStreamError: string | null = null;

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
                } else if (
                  chunk.type === "response.completed" &&
                  chunk.response?.id
                ) {
                  // An OpenAI Responses stream carries no top-level id — it is
                  // on the response object of the terminal event. Langflow's SSE
                  // wrapper does send one, so only the direct (langflowless)
                  // path was affected: without this the caller never learns the
                  // id, never sends previous_response_id, and every question
                  // starts a fresh conversation with no memory of the last turn.
                  newResponseId = chunk.response.id;
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

                const streamError = extractStreamProviderError(chunk);
                if (streamError) {
                  console.error("Error detected in stream", streamError);
                  providerStreamError = streamError;
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

      // Prefer accumulated stream text when it carries the real provider dump —
      // Langflow often sends finish_reason=error with an empty error payload.
      if (content.value && looksLikeProviderErrorContent(content.value)) {
        throw Object.assign(
          new Error(formatProviderErrorMessage(content.value)),
          { partialContent: content.value },
        );
      }

      if (providerStreamError) {
        throw Object.assign(new Error(providerStreamError), {
          partialContent: content.value,
        });
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
      let errorContent = formatProviderErrorMessage(
        errorMessage || "An error occurred while generating a response.",
      );

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

      // Keep any mid-stream partial answer visible above the provider error,
      // unless the "partial" is itself a provider failure dump with JSON.
      const partialContent =
        typeof (error as { partialContent?: unknown }).partialContent ===
        "string"
          ? (error as { partialContent: string }).partialContent.trim()
          : "";
      const partialLooksLikeProviderError =
        partialContent.includes("{") ||
        /api key|authenticat|unauthorized|permission denied|rate limit/i.test(
          partialContent,
        );
      if (
        partialContent &&
        !partialLooksLikeProviderError &&
        !errorContent.startsWith(partialContent) &&
        !errorMessage?.includes("timed out") &&
        !errorMessage?.includes("No response") &&
        !errorMessage?.includes("NetworkError") &&
        !errorMessage?.includes("Failed to fetch")
      ) {
        errorContent = `${partialContent}\n\n${errorContent}`;
      }

      const errorMessageObj: Message = {
        role: "assistant",
        content: errorContent,
        timestamp: new Date(),
        isStreaming: false,
        error: true,
      };

      // onError owns side effects (flags, session reset). onComplete owns appending
      // the error message and refreshing history — pass any stream/store id so a
      // failed first turn still appears in the conversation list.
      onError?.(
        Object.assign(new Error(errorContent), {
          partialContent,
        }) as Error,
      );
      // User aborts skip completion; timeout aborts still surface the error card.
      const isTimeout = errorMessage?.includes("timed out");
      if (!streamAbortRef.current?.signal.aborted || isTimeout) {
        onComplete?.(errorMessageObj, newResponseId);
        refreshConversations(true);
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
