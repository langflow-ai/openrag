"use client";

import { Loader2, Zap } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { StickToBottom, useStickToBottomContext } from "use-stick-to-bottom";
import { ProtectedRoute } from "@/components/protected-route";
import { Button } from "@/components/ui/button";
import { type EndpointType, useChat } from "@/contexts/chat-context";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useTask } from "@/contexts/task-context";
import { useChatStreaming } from "@/hooks/useChatStreaming";
import { FILES_REGEX } from "@/lib/constants";
import { useLoadingStore } from "@/stores/loadingStore";
import { useGetNudgesQuery } from "../api/queries/useGetNudgesQuery";
import { AssistantMessage } from "./components/assistant-message";
import { ChatInput, type ChatInputHandle } from "./components/chat-input";
import { UserMessage } from "./components/user-message";
import Nudges from "./nudges";
import type {
  FunctionCall,
  KnowledgeFilterData,
  Message,
  RequestBody,
  SelectedFilters,
  ToolCallResult,
} from "./types";

function ChatPage() {
  const isDebugMode = process.env.NEXT_PUBLIC_OPENRAG_DEBUG === "true";
  const {
    endpoint,
    setEndpoint,
    currentConversationId,
    conversationData,
    setCurrentConversationId,
    addConversationDoc,
    forkFromResponse,
    refreshConversations,
    refreshConversationsSilent,
    previousResponseIds,
    setPreviousResponseIds,
    placeholderConversation,
  } = useChat();
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content: "How can I assist?",
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState("");
  const { loading, setLoading } = useLoadingStore();
  const [asyncMode, setAsyncMode] = useState(true);
  const [expandedFunctionCalls, setExpandedFunctionCalls] = useState<
    Set<string>
  >(new Set());
  // previousResponseIds now comes from useChat context
  const [isUploading, setIsUploading] = useState(false);
  const [isFilterDropdownOpen, setIsFilterDropdownOpen] = useState(false);
  const [availableFilters, setAvailableFilters] = useState<
    KnowledgeFilterData[]
  >([]);
  const [filterSearchTerm, setFilterSearchTerm] = useState("");
  const [selectedFilterIndex, setSelectedFilterIndex] = useState(0);
  const [isFilterHighlighted, setIsFilterHighlighted] = useState(false);
  const [dropdownDismissed, setDropdownDismissed] = useState(false);
  const [isUserInteracting, setIsUserInteracting] = useState(false);
  const [isForkingInProgress, setIsForkingInProgress] = useState(false);
  const [anchorPosition, setAnchorPosition] = useState<{
    x: number;
    y: number;
  } | null>(null);
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);

  const chatInputRef = useRef<ChatInputHandle>(null);

  const { scrollToBottom } = useStickToBottomContext();

  const lastLoadedConversationRef = useRef<string | null>(null);
  const { addTask } = useTask();
  const { selectedFilter, parsedFilterData, setSelectedFilter } =
    useKnowledgeFilter();

  // Use the chat streaming hook
  const apiEndpoint = endpoint === "chat" ? "/api/chat" : "/api/langflow";
  const {
    streamingMessage,
    sendMessage: sendStreamingMessage,
    abortStream,
  } = useChatStreaming({
    endpoint: apiEndpoint,
    onComplete: (message, responseId) => {
      setMessages((prev) => [...prev, message]);
      setLoading(false);

      if (responseId) {
        cancelNudges();
        setPreviousResponseIds((prev) => ({
          ...prev,
          [endpoint]: responseId,
        }));

        if (!currentConversationId) {
          setCurrentConversationId(responseId);
          refreshConversations(true);
        } else {
          refreshConversationsSilent();
        }
      }
    },
    onError: (error) => {
      console.error("Streaming error:", error);
      setLoading(false);
      const errorMessage: Message = {
        role: "assistant",
        content:
          "Sorry, I couldn't connect to the chat service. Please try again.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    },
  });

  const getCursorPosition = (textarea: HTMLTextAreaElement) => {
    // Create a hidden div with the same styles as the textarea
    const div = document.createElement("div");
    const computedStyle = getComputedStyle(textarea);

    // Copy all computed styles to the hidden div
    for (const style of computedStyle) {
      (div.style as unknown as Record<string, string>)[style] =
        computedStyle.getPropertyValue(style);
    }

    // Set the div to be hidden but not un-rendered
    div.style.position = "absolute";
    div.style.visibility = "hidden";
    div.style.whiteSpace = "pre-wrap";
    div.style.wordWrap = "break-word";
    div.style.overflow = "hidden";
    div.style.height = "auto";
    div.style.width = `${textarea.getBoundingClientRect().width}px`;

    // Get the text up to the cursor position
    const cursorPos = textarea.selectionStart || 0;
    const textBeforeCursor = textarea.value.substring(0, cursorPos);

    // Add the text before cursor
    div.textContent = textBeforeCursor;

    // Create a span to mark the end position
    const span = document.createElement("span");
    span.textContent = "|"; // Cursor marker
    div.appendChild(span);

    // Add the text after cursor to handle word wrapping
    const textAfterCursor = textarea.value.substring(cursorPos);
    div.appendChild(document.createTextNode(textAfterCursor));

    // Add the div to the document temporarily
    document.body.appendChild(div);

    // Get positions
    const inputRect = textarea.getBoundingClientRect();
    const divRect = div.getBoundingClientRect();
    const spanRect = span.getBoundingClientRect();

    // Calculate the cursor position relative to the input
    const x = inputRect.left + (spanRect.left - divRect.left);
    const y = inputRect.top + (spanRect.top - divRect.top);

    // Clean up
    document.body.removeChild(div);

    return { x, y };
  };

  const handleEndpointChange = (newEndpoint: EndpointType) => {
    setEndpoint(newEndpoint);
    // Clear the conversation when switching endpoints to avoid response ID conflicts
    setMessages([]);
    setPreviousResponseIds({ chat: null, langflow: null });
  };

  const handleFileUpload = async (file: File) => {
    console.log("handleFileUpload called with file:", file.name);

    if (isUploading) return;

    setIsUploading(true);
    setLoading(true);

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("endpoint", endpoint);

      // Add previous_response_id if we have one for this endpoint
      const currentResponseId = previousResponseIds[endpoint];
      if (currentResponseId) {
        formData.append("previous_response_id", currentResponseId);
      }

      const response = await fetch("/api/upload_context", {
        method: "POST",
        body: formData,
      });

      console.log("Upload response status:", response.status);

      if (!response.ok) {
        const errorText = await response.text();
        console.error(
          "Upload failed with status:",
          response.status,
          "Response:",
          errorText,
        );
        throw new Error("Failed to process document");
      }

      const result = await response.json();
      console.log("Upload result:", result);

      if (response.status === 201) {
        // New flow: Got task ID, start tracking with centralized system
        const taskId = result.task_id || result.id;

        if (!taskId) {
          console.error("No task ID in 201 response:", result);
          throw new Error("No task ID received from server");
        }

        // Add task to centralized tracking
        addTask(taskId);

        return null;
      } else if (response.ok) {
        // Original flow: Direct response

        const uploadMessage: Message = {
          role: "user",
          content: `I'm uploading a document called "${result.filename}". Here is its content:`,
          timestamp: new Date(),
        };

		const confirmationMessage: Message = {
			role: "assistant",
			content: `Confirmed`,
			timestamp: new Date(),
		  };
  

        setMessages((prev) => [...prev, uploadMessage, confirmationMessage]);

        // Add file to conversation docs
        if (result.filename) {
          addConversationDoc(result.filename);
        }

        // Update the response ID for this endpoint
        if (result.response_id) {
          setPreviousResponseIds((prev) => ({
            ...prev,
            [endpoint]: result.response_id,
          }));

          // If this is a new conversation (no currentConversationId), set it now
          if (!currentConversationId) {
            setCurrentConversationId(result.response_id);
            refreshConversations(true);
          } else {
            // For existing conversations, do a silent refresh to keep backend in sync
            refreshConversationsSilent();
          }

          return result.response_id;
        }
      } else {
        throw new Error(`Upload failed: ${response.status}`);
      }
    } catch (error) {
      console.error("Upload failed:", error);
      const errorMessage: Message = {
        role: "assistant",
        content: `❌ Failed to process document. Please try again.`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev.slice(0, -1), errorMessage]);
    } finally {
      setIsUploading(false);
      setLoading(false);
    }
  };

  const handleFilePickerClick = () => {
    chatInputRef.current?.clickFileInput();
  };

  const loadAvailableFilters = async () => {
    try {
      const response = await fetch("/api/knowledge-filter/search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query: "",
          limit: 20,
        }),
      });

      const result = await response.json();
      if (response.ok && result.success) {
        setAvailableFilters(result.filters);
      } else {
        console.error("Failed to load knowledge filters:", result.error);
        setAvailableFilters([]);
      }
    } catch (error) {
      console.error("Failed to load knowledge filters:", error);
      setAvailableFilters([]);
    }
  };

  const handleFilterSelect = (filter: KnowledgeFilterData | null) => {
    setSelectedFilter(filter);
    setIsFilterDropdownOpen(false);
    setFilterSearchTerm("");
    setIsFilterHighlighted(false);

    // Remove the @searchTerm from the input and replace with filter pill
    const words = input.split(" ");
    const lastWord = words[words.length - 1];

    if (lastWord.startsWith("@")) {
      // Remove the @search term
      words.pop();
      setInput(words.join(" ") + (words.length > 0 ? " " : ""));
    }
  };

  // Reset selected index when search term changes
  useEffect(() => {
    setSelectedFilterIndex(0);
  }, []);

  // Auto-focus the input on component mount
  useEffect(() => {
    chatInputRef.current?.focusInput();
  }, []);

  // Explicitly handle external new conversation trigger
  useEffect(() => {
    const handleNewConversation = () => {
      // Abort any in-flight streaming so it doesn't bleed into new chat
      abortStream();
      // Reset chat UI even if context state was already 'new'
      setMessages([
        {
          role: "assistant",
          content: "How can I assist?",
          timestamp: new Date(),
        },
      ]);
      setInput("");
      setExpandedFunctionCalls(new Set());
      setIsFilterHighlighted(false);
      setLoading(false);
      lastLoadedConversationRef.current = null;
    };

    const handleFocusInput = () => {
      chatInputRef.current?.focusInput();
    };

    window.addEventListener("newConversation", handleNewConversation);
    window.addEventListener("focusInput", handleFocusInput);
    return () => {
      window.removeEventListener("newConversation", handleNewConversation);
      window.removeEventListener("focusInput", handleFocusInput);
    };
  }, [abortStream, setLoading]);

  // Load conversation only when user explicitly selects a conversation
  useEffect(() => {
    // Only load conversation data when:
    // 1. conversationData exists AND
    // 2. It's different from the last loaded conversation AND
    // 3. User is not in the middle of an interaction
    if (
      conversationData &&
      conversationData.messages &&
      lastLoadedConversationRef.current !== conversationData.response_id &&
      !isUserInteracting &&
      !isForkingInProgress
    ) {
      console.log(
        "Loading conversation with",
        conversationData.messages.length,
        "messages",
      );
      // Convert backend message format to frontend Message interface
      const convertedMessages: Message[] = conversationData.messages.map(
        (msg: {
          role: string;
          content: string;
          timestamp?: string;
          response_id?: string;
          chunks?: Array<{
            item?: {
              type?: string;
              tool_name?: string;
              id?: string;
              inputs?: unknown;
              results?: unknown;
              status?: string;
            };
            delta?: {
              tool_calls?: Array<{
                id?: string;
                function?: { name?: string; arguments?: string };
                type?: string;
              }>;
            };
            type?: string;
            result?: unknown;
            output?: unknown;
            response?: unknown;
          }>;
          response_data?: unknown;
        }) => {
          const message: Message = {
            role: msg.role as "user" | "assistant",
            content: msg.content,
            timestamp: new Date(msg.timestamp || new Date()),
          };

          // Extract function calls from chunks or response_data
          if (msg.role === "assistant" && (msg.chunks || msg.response_data)) {
            const functionCalls: FunctionCall[] = [];
            console.log("Processing assistant message for function calls:", {
              hasChunks: !!msg.chunks,
              chunksLength: msg.chunks?.length,
              hasResponseData: !!msg.response_data,
            });

            // Process chunks (streaming data)
            if (msg.chunks && Array.isArray(msg.chunks)) {
              for (const chunk of msg.chunks) {
                // Handle Langflow format: chunks[].item.tool_call
                if (chunk.item && chunk.item.type === "tool_call") {
                  const toolCall = chunk.item;
                  console.log("Found Langflow tool call:", toolCall);
                  functionCalls.push({
                    id: toolCall.id || "",
                    name: toolCall.tool_name || "unknown",
                    arguments:
                      (toolCall.inputs as Record<string, unknown>) || {},
                    argumentsString: JSON.stringify(toolCall.inputs || {}),
                    result: toolCall.results as
                      | Record<string, unknown>
                      | ToolCallResult[],
                    status:
                      (toolCall.status as "pending" | "completed" | "error") ||
                      "completed",
                    type: "tool_call",
                  });
                }
                // Handle OpenAI format: chunks[].delta.tool_calls
                else if (chunk.delta?.tool_calls) {
                  for (const toolCall of chunk.delta.tool_calls) {
                    if (toolCall.function) {
                      functionCalls.push({
                        id: toolCall.id || "",
                        name: toolCall.function.name || "unknown",
                        arguments: toolCall.function.arguments
                          ? JSON.parse(toolCall.function.arguments)
                          : {},
                        argumentsString: toolCall.function.arguments || "",
                        status: "completed",
                        type: toolCall.type || "function",
                      });
                    }
                  }
                }
                // Process tool call results from chunks
                if (
                  chunk.type === "response.tool_call.result" ||
                  chunk.type === "tool_call_result"
                ) {
                  const lastCall = functionCalls[functionCalls.length - 1];
                  if (lastCall) {
                    lastCall.result =
                      (chunk.result as
                        | Record<string, unknown>
                        | ToolCallResult[]) ||
                      (chunk as Record<string, unknown>);
                    lastCall.status = "completed";
                  }
                }
              }
            }

            // Process response_data (non-streaming data)
            if (msg.response_data && typeof msg.response_data === "object") {
              // Look for tool_calls in various places in the response data
              const responseData =
                typeof msg.response_data === "string"
                  ? JSON.parse(msg.response_data)
                  : msg.response_data;

              if (
                responseData.tool_calls &&
                Array.isArray(responseData.tool_calls)
              ) {
                for (const toolCall of responseData.tool_calls) {
                  functionCalls.push({
                    id: toolCall.id,
                    name: toolCall.function?.name || toolCall.name,
                    arguments:
                      toolCall.function?.arguments || toolCall.arguments,
                    argumentsString:
                      typeof (
                        toolCall.function?.arguments || toolCall.arguments
                      ) === "string"
                        ? toolCall.function?.arguments || toolCall.arguments
                        : JSON.stringify(
                            toolCall.function?.arguments || toolCall.arguments,
                          ),
                    result: toolCall.result,
                    status: "completed",
                    type: toolCall.type || "function",
                  });
                }
              }
            }

            if (functionCalls.length > 0) {
              console.log("Setting functionCalls on message:", functionCalls);
              message.functionCalls = functionCalls;
            } else {
              console.log("No function calls found in message");
            }
          }

          return message;
        },
      );

      setMessages(convertedMessages);
      lastLoadedConversationRef.current = conversationData.response_id;

      // Set the previous response ID for this conversation
      setPreviousResponseIds((prev) => ({
        ...prev,
        [conversationData.endpoint]: conversationData.response_id,
      }));
    }
  }, [
    conversationData,
    isUserInteracting,
    isForkingInProgress,
    setPreviousResponseIds,
  ]);

  // Handle new conversation creation - only reset messages when placeholderConversation is set
  useEffect(() => {
    if (placeholderConversation && currentConversationId === null) {
      console.log("Starting new conversation");
      setMessages([
        {
          role: "assistant",
          content: "How can I assist?",
          timestamp: new Date(),
        },
      ]);
      lastLoadedConversationRef.current = null;
    }
  }, [placeholderConversation, currentConversationId]);

  // Listen for file upload events from navigation
  useEffect(() => {
    const handleFileUploadStart = (event: CustomEvent) => {
      const { filename } = event.detail;
      console.log("Chat page received file upload start event:", filename);

      setLoading(true);
      setIsUploading(true);
      setUploadedFile(null); // Clear previous file

      // Add initial upload message
      const uploadStartMessage: Message = {
        role: "assistant",
        content: `🔄 Starting upload of **${filename}**...`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, uploadStartMessage]);
    };

    const handleFileUploaded = (event: CustomEvent) => {
      const { result } = event.detail;
      console.log("Chat page received file upload event:", result);

      // Replace the last message with upload complete message
      const uploadMessage: Message = {
        role: "assistant",
        content: `📄 Document uploaded: **${result.filename}** (${
          result.pages
        } pages, ${result.content_length.toLocaleString()} characters)\n\n${
          result.confirmation
        }`,
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev.slice(0, -1), uploadMessage]);
      setUploadedFile(null); // Clear file after upload

      // Update the response ID for this endpoint
      if (result.response_id) {
        setPreviousResponseIds((prev) => ({
          ...prev,
          [endpoint]: result.response_id,
        }));
      }
    };

    const handleFileUploadComplete = () => {
      console.log("Chat page received file upload complete event");
      setLoading(false);
      setIsUploading(false);
    };

    const handleFileUploadError = (event: CustomEvent) => {
      const { filename, error } = event.detail;
      console.log(
        "Chat page received file upload error event:",
        filename,
        error,
      );

      // Replace the last message with error message
      const errorMessage: Message = {
        role: "assistant",
        content: `❌ Upload failed for **${filename}**: ${error}`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev.slice(0, -1), errorMessage]);
      setUploadedFile(null); // Clear file on error
    };

    window.addEventListener(
      "fileUploadStart",
      handleFileUploadStart as EventListener,
    );
    window.addEventListener(
      "fileUploaded",
      handleFileUploaded as EventListener,
    );
    window.addEventListener(
      "fileUploadComplete",
      handleFileUploadComplete as EventListener,
    );
    window.addEventListener(
      "fileUploadError",
      handleFileUploadError as EventListener,
    );

    return () => {
      window.removeEventListener(
        "fileUploadStart",
        handleFileUploadStart as EventListener,
      );
      window.removeEventListener(
        "fileUploaded",
        handleFileUploaded as EventListener,
      );
      window.removeEventListener(
        "fileUploadComplete",
        handleFileUploadComplete as EventListener,
      );
      window.removeEventListener(
        "fileUploadError",
        handleFileUploadError as EventListener,
      );
    };
  }, [endpoint, setPreviousResponseIds, setLoading]);

  // Check if onboarding is complete by looking at local storage
  const [isOnboardingComplete, setIsOnboardingComplete] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("onboarding-step") === null;
  });

  // Listen for storage changes to detect when onboarding completes
  useEffect(() => {
    const checkOnboarding = () => {
      if (typeof window !== "undefined") {
        setIsOnboardingComplete(
          localStorage.getItem("onboarding-step") === null,
        );
      }
    };

    // Check periodically since storage events don't fire in the same tab
    const interval = setInterval(checkOnboarding, 500);

    return () => clearInterval(interval);
  }, []);

  const { data: nudges = [], cancel: cancelNudges } = useGetNudgesQuery(
    previousResponseIds[endpoint],
    {
      enabled: isOnboardingComplete, // Only fetch nudges after onboarding is complete
    },
  );

  const handleSSEStream = async (
    userMessage: Message,
    previousResponseId?: string,
  ) => {
    // Prepare filters
    const processedFilters = parsedFilterData?.filters
      ? (() => {
          const filters = parsedFilterData.filters;
          const processed: SelectedFilters = {
            data_sources: [],
            document_types: [],
            owners: [],
          };
          processed.data_sources = filters.data_sources.includes("*")
            ? []
            : filters.data_sources;
          processed.document_types = filters.document_types.includes("*")
            ? []
            : filters.document_types;
          processed.owners = filters.owners.includes("*") ? [] : filters.owners;

          const hasFilters =
            processed.data_sources.length > 0 ||
            processed.document_types.length > 0 ||
            processed.owners.length > 0;
          return hasFilters ? processed : undefined;
        })()
      : undefined;

    // Use passed previousResponseId if available, otherwise fall back to state
    const responseIdToUse = previousResponseId || previousResponseIds[endpoint];

    // Use the hook to send the message
    await sendStreamingMessage({
      prompt: userMessage.content,
      previousResponseId: responseIdToUse || undefined,
      filters: processedFilters,
      limit: parsedFilterData?.limit ?? 10,
      scoreThreshold: parsedFilterData?.scoreThreshold ?? 0,
    });
    scrollToBottom({
      animation: "smooth",
      duration: 1000,
    });
  };

  const handleSendMessage = async (
    inputMessage: string,
    previousResponseId?: string,
  ) => {
    if (!inputMessage.trim() || loading) return;

    const userMessage: Message = {
      role: "user",
      content: inputMessage.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);
    setIsFilterHighlighted(false);

    scrollToBottom({
      animation: "smooth",
      duration: 1000,
    });

    if (asyncMode) {
      await handleSSEStream(userMessage, previousResponseId);
    } else {
      // Original non-streaming logic
      try {
        const apiEndpoint = endpoint === "chat" ? "/api/chat" : "/api/langflow";

        const requestBody: RequestBody = {
          prompt: userMessage.content,
          ...(parsedFilterData?.filters &&
            (() => {
              const filters = parsedFilterData.filters;
              const processed: SelectedFilters = {
                data_sources: [],
                document_types: [],
                owners: [],
              };
              // Only copy non-wildcard arrays
              processed.data_sources = filters.data_sources.includes("*")
                ? []
                : filters.data_sources;
              processed.document_types = filters.document_types.includes("*")
                ? []
                : filters.document_types;
              processed.owners = filters.owners.includes("*")
                ? []
                : filters.owners;

              // Only include filters if any array has values
              const hasFilters =
                processed.data_sources.length > 0 ||
                processed.document_types.length > 0 ||
                processed.owners.length > 0;
              return hasFilters ? { filters: processed } : {};
            })()),
          limit: parsedFilterData?.limit ?? 10,
          scoreThreshold: parsedFilterData?.scoreThreshold ?? 0,
        };

        // Add previous_response_id if we have one for this endpoint
        const currentResponseId = previousResponseIds[endpoint];
        if (currentResponseId) {
          requestBody.previous_response_id = currentResponseId;
        }

        const response = await fetch(apiEndpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(requestBody),
        });

        const result = await response.json();

        if (response.ok) {
          const assistantMessage: Message = {
            role: "assistant",
            content: result.response,
            timestamp: new Date(),
          };
          setMessages((prev) => [...prev, assistantMessage]);
          if (result.response_id) {
            cancelNudges();
          }

          // Store the response ID if present for this endpoint
          if (result.response_id) {
            setPreviousResponseIds((prev) => ({
              ...prev,
              [endpoint]: result.response_id,
            }));

            // If this is a new conversation (no currentConversationId), set it now
            if (!currentConversationId) {
              setCurrentConversationId(result.response_id);
              refreshConversations(true);
            } else {
              // For existing conversations, do a silent refresh to keep backend in sync
              refreshConversationsSilent();
            }
          }
        } else {
          console.error("Chat failed:", result.error);
          const errorMessage: Message = {
            role: "assistant",
            content: "Sorry, I encountered an error. Please try again.",
            timestamp: new Date(),
          };
          setMessages((prev) => [...prev, errorMessage]);
        }
      } catch (error) {
        console.error("Chat error:", error);
        const errorMessage: Message = {
          role: "assistant",
          content:
            "Sorry, I couldn't connect to the chat service. Please try again.",
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, errorMessage]);
      }
    }

    setLoading(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Check if there's an uploaded file and upload it first
    let uploadedResponseId: string | null = null;
    if (uploadedFile) {
      // Upload the file first
      const responseId = await handleFileUpload(uploadedFile);
      // Clear the file after upload
      setUploadedFile(null);

      // If the upload resulted in a new conversation, store the response ID
      if (responseId) {
        uploadedResponseId = responseId;
        setPreviousResponseIds((prev) => ({
          ...prev,
          [endpoint]: responseId,
        }));
      }
    }

    // Only send message if there's input text
    if (input.trim()) {
      // Pass the responseId from upload (if any) to handleSendMessage
      handleSendMessage(input, uploadedResponseId || undefined);
    }
  };

  const toggleFunctionCall = (functionCallId: string) => {
    setExpandedFunctionCalls((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(functionCallId)) {
        newSet.delete(functionCallId);
      } else {
        newSet.add(functionCallId);
      }
      return newSet;
    });
  };

  const handleForkConversation = (
    messageIndex: number,
    event?: React.MouseEvent,
  ) => {
    // Prevent any default behavior and stop event propagation
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }

    // Set interaction state to prevent auto-scroll interference
    setIsUserInteracting(true);
    setIsForkingInProgress(true);

    console.log("Fork conversation called for message index:", messageIndex);

    // Get messages up to and including the selected assistant message
    const messagesToKeep = messages.slice(0, messageIndex + 1);

    // The selected message should be an assistant message (since fork button is only on assistant messages)
    const forkedMessage = messages[messageIndex];
    if (forkedMessage.role !== "assistant") {
      console.error("Fork button should only be on assistant messages");
      setIsUserInteracting(false);
      setIsForkingInProgress(false);
      return;
    }

    // For forking, we want to continue from the response_id of the assistant message we're forking from
    // Since we don't store individual response_ids per message yet, we'll use the current conversation's response_id
    // This means we're continuing the conversation thread from that point
    const responseIdToForkFrom =
      currentConversationId || previousResponseIds[endpoint];

    // Create a new conversation by properly forking
    setMessages(messagesToKeep);

    // Use the chat context's fork method which handles creating a new conversation properly
    if (forkFromResponse) {
      forkFromResponse(responseIdToForkFrom || "");
    } else {
      // Fallback to manual approach
      setCurrentConversationId(null); // This creates a new conversation thread

      // Set the response_id we want to continue from as the previous response ID
      // This tells the backend to continue the conversation from this point
      setPreviousResponseIds((prev) => ({
        ...prev,
        [endpoint]: responseIdToForkFrom,
      }));
    }

    console.log("Forked conversation with", messagesToKeep.length, "messages");

    // Reset interaction state after a longer delay to ensure all effects complete
    setTimeout(() => {
      setIsUserInteracting(false);
      setIsForkingInProgress(false);
      console.log("Fork interaction complete, re-enabling auto effects");
    }, 500);

    // The original conversation remains unchanged in the sidebar
    // This new forked conversation will get its own response_id when the user sends the next message
  };

  const handleSuggestionClick = (suggestion: string) => {
    handleSendMessage(suggestion);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Handle backspace for filter clearing
    if (e.key === "Backspace" && selectedFilter && input.trim() === "") {
      e.preventDefault();

      if (isFilterHighlighted) {
        // Second backspace - remove the filter
        setSelectedFilter(null);
        setIsFilterHighlighted(false);
      } else {
        // First backspace - highlight the filter
        setIsFilterHighlighted(true);
      }
      return;
    }

    if (isFilterDropdownOpen) {
      const filteredFilters = availableFilters.filter((filter) =>
        filter.name.toLowerCase().includes(filterSearchTerm.toLowerCase()),
      );

      if (e.key === "Escape") {
        e.preventDefault();
        setIsFilterDropdownOpen(false);
        setFilterSearchTerm("");
        setSelectedFilterIndex(0);
        setDropdownDismissed(true);

        // Keep focus on the textarea so user can continue typing normally
        chatInputRef.current?.focusInput();
        return;
      }

      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedFilterIndex((prev) =>
          prev < filteredFilters.length - 1 ? prev + 1 : 0,
        );
        return;
      }

      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedFilterIndex((prev) =>
          prev > 0 ? prev - 1 : filteredFilters.length - 1,
        );
        return;
      }

      if (e.key === "Enter") {
        // Check if we're at the end of an @ mention (space before cursor or end of input)
        const cursorPos = e.currentTarget.selectionStart || 0;
        const textBeforeCursor = input.slice(0, cursorPos);
        const words = textBeforeCursor.split(" ");
        const lastWord = words[words.length - 1];

        if (lastWord.startsWith("@") && filteredFilters[selectedFilterIndex]) {
          e.preventDefault();
          handleFilterSelect(filteredFilters[selectedFilterIndex]);
          return;
        }
      }

      if (e.key === " ") {
        // Select filter on space if we're typing an @ mention
        const cursorPos = e.currentTarget.selectionStart || 0;
        const textBeforeCursor = input.slice(0, cursorPos);
        const words = textBeforeCursor.split(" ");
        const lastWord = words[words.length - 1];

        if (lastWord.startsWith("@") && filteredFilters[selectedFilterIndex]) {
          e.preventDefault();
          handleFilterSelect(filteredFilters[selectedFilterIndex]);
          return;
        }
      }
    }

    if (e.key === "Enter" && !e.shiftKey && !isFilterDropdownOpen) {
      e.preventDefault();
      if (input.trim() && !loading) {
        // Trigger form submission by finding the form and calling submit
        const form = e.currentTarget.closest("form");
        if (form) {
          form.requestSubmit();
        }
      }
    }
  };

  const onChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value;
    setInput(newValue);

    // Clear filter highlight when user starts typing
    if (isFilterHighlighted) {
      setIsFilterHighlighted(false);
    }

    // Find if there's an @ at the start of the last word
    const words = newValue.split(" ");
    const lastWord = words[words.length - 1];

    if (lastWord.startsWith("@") && !dropdownDismissed) {
      const searchTerm = lastWord.slice(1); // Remove the @
      console.log("Setting search term:", searchTerm);
      setFilterSearchTerm(searchTerm);
      setSelectedFilterIndex(0);

      // Only set anchor position when @ is first detected (search term is empty)
      if (searchTerm === "") {
        const pos = getCursorPosition(e.target);
        setAnchorPosition(pos);
      }

      if (!isFilterDropdownOpen) {
        loadAvailableFilters();
        setIsFilterDropdownOpen(true);
      }
    } else if (isFilterDropdownOpen) {
      // Close dropdown if @ is no longer present
      console.log("Closing dropdown - no @ found");
      setIsFilterDropdownOpen(false);
      setFilterSearchTerm("");
    }

    // Reset dismissed flag when user moves to a different word
    if (dropdownDismissed && !lastWord.startsWith("@")) {
      setDropdownDismissed(false);
    }
  };

  const onAtClick = () => {
    if (!isFilterDropdownOpen) {
      loadAvailableFilters();
      setIsFilterDropdownOpen(true);
      setFilterSearchTerm("");
      setSelectedFilterIndex(0);

      // Get button position for popover anchoring
      const button = document.querySelector(
        "[data-filter-button]",
      ) as HTMLElement;
      if (button) {
        const rect = button.getBoundingClientRect();
        setAnchorPosition({
          x: rect.left + rect.width / 2,
          y: rect.top + rect.height / 2 - 12,
        });
      }
    } else {
      setIsFilterDropdownOpen(false);
      setAnchorPosition(null);
    }
  };

  return (
    <>
      {/* Debug header - only show in debug mode */}
      {isDebugMode && (
        <div className="flex items-center justify-between p-6">
          <div className="flex items-center gap-2"></div>
          <div className="flex items-center gap-4">
            {/* Async Mode Toggle */}
            <div className="flex items-center gap-2 bg-muted/50 rounded-lg p-1">
              <Button
                variant={!asyncMode ? "default" : "ghost"}
                size="sm"
                onClick={() => setAsyncMode(false)}
                className="h-7 text-xs"
              >
                Streaming Off
              </Button>
              <Button
                variant={asyncMode ? "default" : "ghost"}
                size="sm"
                onClick={() => setAsyncMode(true)}
                className="h-7 text-xs"
              >
                <Zap className="h-3 w-3 mr-1" />
                Streaming On
              </Button>
            </div>
            {/* Endpoint Toggle */}
            <div className="flex items-center gap-2 bg-muted/50 rounded-lg p-1">
              <Button
                variant={endpoint === "chat" ? "default" : "ghost"}
                size="sm"
                onClick={() => handleEndpointChange("chat")}
                className="h-7 text-xs"
              >
                Chat
              </Button>
              <Button
                variant={endpoint === "langflow" ? "default" : "ghost"}
                size="sm"
                onClick={() => handleEndpointChange("langflow")}
                className="h-7 text-xs"
              >
                Langflow
              </Button>
            </div>
          </div>
        </div>
      )}

      <StickToBottom.Content className="flex flex-col min-h-full overflow-x-hidden p-6">
        <div className="flex flex-col place-self-center space-y-6 max-w-[960px] w-full mx-auto">
          {messages.length === 0 && !streamingMessage ? (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              <div className="text-center">
                {isUploading ? (
                  <>
                    <Loader2 className="h-12 w-12 mx-auto mb-4 animate-spin" />
                    <p>Processing your document...</p>
                    <p className="text-sm mt-2">This may take a few moments</p>
                  </>
                ) : null}
              </div>
            </div>
          ) : (
            <>
              {messages.map((message, index) =>
                message.role === "user"
                  ? (messages[index]?.content.match(FILES_REGEX)?.[0] ??
                      null) === null && (
                      <div
                        key={`${
                          message.role
                        }-${index}-${message.timestamp?.getTime()}`}
                        className="space-y-6 group"
                      >
                        <UserMessage
                          animate={
                            message.source
                              ? message.source !== "langflow"
                              : false
                          }
                          content={message.content}
                          files={
                            index >= 2
                              ? messages[index - 2]?.content.match(
                                  FILES_REGEX,
                                )?.[0] ?? undefined
                              : undefined
                          }
                        />
                      </div>
                    )
                  : message.role === "assistant" &&
                    (index < 1 ||
                      (messages[index - 1]?.content.match(FILES_REGEX)?.[0] ??
                        null) === null) && (
                      <div
                        key={`${
                          message.role
                        }-${index}-${message.timestamp?.getTime()}`}
                        className="space-y-6 group"
                      >
                        <AssistantMessage
                          content={message.content}
                          functionCalls={message.functionCalls}
                          messageIndex={index}
                          expandedFunctionCalls={expandedFunctionCalls}
                          onToggle={toggleFunctionCall}
                          showForkButton={endpoint === "chat"}
                          onFork={(e) => handleForkConversation(index, e)}
                          animate={false}
                          isInactive={index < messages.length - 1}
                        />
                      </div>
                    ),
              )}

              {/* Streaming Message Display */}
              {streamingMessage && (
                <AssistantMessage
                  content={streamingMessage.content}
                  functionCalls={streamingMessage.functionCalls}
                  messageIndex={messages.length}
                  expandedFunctionCalls={expandedFunctionCalls}
                  onToggle={toggleFunctionCall}
                  delay={0.4}
                  isStreaming
                  isCompleted={false}
                />
              )}
            </>
          )}
          {!streamingMessage && (
            <div className="pl-10">
              <Nudges
                nudges={loading ? [] : (nudges as string[])}
                handleSuggestionClick={handleSuggestionClick}
              />
            </div>
          )}
        </div>
      </StickToBottom.Content>
      <div className="p-6 pt-0 max-w-[960px] mx-auto w-full">
        {/* Input Area - Fixed at bottom */}
        <ChatInput
          ref={chatInputRef}
          input={input}
          loading={loading}
          isUploading={isUploading}
          selectedFilter={selectedFilter}
          isFilterDropdownOpen={isFilterDropdownOpen}
          availableFilters={availableFilters}
          filterSearchTerm={filterSearchTerm}
          selectedFilterIndex={selectedFilterIndex}
          anchorPosition={anchorPosition}
          parsedFilterData={parsedFilterData}
          uploadedFile={uploadedFile}
          onSubmit={handleSubmit}
          onChange={onChange}
          onKeyDown={handleKeyDown}
          onFilterSelect={handleFilterSelect}
          onAtClick={onAtClick}
          onFilePickerClick={handleFilePickerClick}
          onFileSelected={setUploadedFile}
          setSelectedFilter={setSelectedFilter}
          setIsFilterHighlighted={setIsFilterHighlighted}
          setIsFilterDropdownOpen={setIsFilterDropdownOpen}
        />
      </div>
    </>
  );
}

export default function ProtectedChatPage() {
  return (
    <ProtectedRoute>
      <div className="flex w-full h-full overflow-hidden">
        <StickToBottom
          className="flex h-full flex-1 flex-col"
          resize="smooth"
          initial="instant"
          mass={1}
        >
          <ChatPage />
        </StickToBottom>
      </div>
    </ProtectedRoute>
  );
}
