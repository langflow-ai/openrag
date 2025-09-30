"use client";

import {
  AtSign,
  Bot,
  ChevronDown,
  ChevronRight,
  GitBranch,
  Loader2,
  Plus,
  Settings,
  Upload,
  User,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { ProtectedRoute } from "@/components/protected-route";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/auth-context";
import { type EndpointType, useChat } from "@/contexts/chat-context";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useTask } from "@/contexts/task-context";
import { useLoadingStore } from "@/stores/loadingStore";
import { useGetNudgesQuery } from "../api/queries/useGetNudgesQuery";
import Nudges from "./nudges";
import { filterAccentClasses } from "@/components/knowledge-filter-panel";

interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  functionCalls?: FunctionCall[];
  isStreaming?: boolean;
}

interface FunctionCall {
  name: string;
  arguments?: Record<string, unknown>;
  result?: Record<string, unknown> | ToolCallResult[];
  status: "pending" | "completed" | "error";
  argumentsString?: string;
  id?: string;
  type?: string;
}

interface ToolCallResult {
  text_key?: string;
  data?: {
    file_path?: string;
    text?: string;
    [key: string]: unknown;
  };
  default_value?: string;
  [key: string]: unknown;
}

interface SelectedFilters {
  data_sources: string[];
  document_types: string[];
  owners: string[];
}

interface KnowledgeFilterData {
  id: string;
  name: string;
  description: string;
  query_data: string;
  owner: string;
  created_at: string;
  updated_at: string;
}

interface RequestBody {
  prompt: string;
  stream?: boolean;
  previous_response_id?: string;
  filters?: SelectedFilters;
  limit?: number;
  scoreThreshold?: number;
}

function ChatPage() {
  const isDebugMode =
    process.env.NODE_ENV === "development" ||
    process.env.NEXT_PUBLIC_OPENRAG_DEBUG === "true";
  const { user } = useAuth();
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
  const [streamingMessage, setStreamingMessage] = useState<{
    content: string;
    functionCalls: FunctionCall[];
    timestamp: Date;
  } | null>(null);
  const [expandedFunctionCalls, setExpandedFunctionCalls] = useState<
    Set<string>
  >(new Set());
  // previousResponseIds now comes from useChat context
  const [isUploading, setIsUploading] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);
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
  const dragCounterRef = useRef(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const streamIdRef = useRef(0);
  const lastLoadedConversationRef = useRef<string | null>(null);
  const { addTask, isMenuOpen } = useTask();
  const { selectedFilter, parsedFilterData, isPanelOpen, setSelectedFilter } =
    useKnowledgeFilter();

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
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

    // Add initial upload message
    const uploadStartMessage: Message = {
      role: "assistant",
      content: `🔄 Starting upload of **${file.name}**...`,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, uploadStartMessage]);

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
          errorText
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

        // Update message to show task is being tracked
        const pollingMessage: Message = {
          role: "assistant",
          content: `⏳ Upload initiated for **${file.name}**. Processing in background... (Task ID: ${taskId})`,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev.slice(0, -1), pollingMessage]);
      } else if (response.ok) {
        // Original flow: Direct response

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

  // Remove the old pollTaskStatus function since we're using centralized system

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current++;
    if (dragCounterRef.current === 1) {
      setIsDragOver(true);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current--;
    if (dragCounterRef.current === 0) {
      setIsDragOver(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
    setIsDragOver(false);

    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      handleFileUpload(files[0]); // Upload first file only
    }
  };

  const handleFilePickerClick = () => {
    fileInputRef.current?.click();
  };

  const handleFilePickerChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFileUpload(files[0]);
    }
    // Reset the input so the same file can be selected again
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
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

  const handleFilterDropdownToggle = () => {
    if (!isFilterDropdownOpen) {
      loadAvailableFilters();
    }
    setIsFilterDropdownOpen(!isFilterDropdownOpen);
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

  useEffect(() => {
    // Only auto-scroll if not in the middle of user interaction
    if (!isUserInteracting) {
      const timer = setTimeout(() => {
        scrollToBottom();
      }, 50); // Small delay to avoid conflicts with click events

      return () => clearTimeout(timer);
    }
  }, [messages, streamingMessage, isUserInteracting]);

  // Reset selected index when search term changes
  useEffect(() => {
    setSelectedFilterIndex(0);
  }, [filterSearchTerm]);

  // Auto-focus the input on component mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Explicitly handle external new conversation trigger
  useEffect(() => {
    const handleNewConversation = () => {
      // Abort any in-flight streaming so it doesn't bleed into new chat
      if (streamAbortRef.current) {
        streamAbortRef.current.abort();
      }
      // Reset chat UI even if context state was already 'new'
      setMessages([
        {
          role: "assistant",
          content: "How can I assist?",
          timestamp: new Date(),
        },
      ]);
      setInput("");
      setStreamingMessage(null);
      setExpandedFunctionCalls(new Set());
      setIsFilterHighlighted(false);
      setLoading(false);
      lastLoadedConversationRef.current = null;
    };

    const handleFocusInput = () => {
      inputRef.current?.focus();
    };

    window.addEventListener("newConversation", handleNewConversation);
    window.addEventListener("focusInput", handleFocusInput);
    return () => {
      window.removeEventListener("newConversation", handleNewConversation);
      window.removeEventListener("focusInput", handleFocusInput);
    };
  }, []);

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
        "messages"
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
                            toolCall.function?.arguments || toolCall.arguments
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
        }
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
        error
      );

      // Replace the last message with error message
      const errorMessage: Message = {
        role: "assistant",
        content: `❌ Upload failed for **${filename}**: ${error}`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev.slice(0, -1), errorMessage]);
    };

    window.addEventListener(
      "fileUploadStart",
      handleFileUploadStart as EventListener
    );
    window.addEventListener(
      "fileUploaded",
      handleFileUploaded as EventListener
    );
    window.addEventListener(
      "fileUploadComplete",
      handleFileUploadComplete as EventListener
    );
    window.addEventListener(
      "fileUploadError",
      handleFileUploadError as EventListener
    );

    return () => {
      window.removeEventListener(
        "fileUploadStart",
        handleFileUploadStart as EventListener
      );
      window.removeEventListener(
        "fileUploaded",
        handleFileUploaded as EventListener
      );
      window.removeEventListener(
        "fileUploadComplete",
        handleFileUploadComplete as EventListener
      );
      window.removeEventListener(
        "fileUploadError",
        handleFileUploadError as EventListener
      );
    };
  }, [endpoint, setPreviousResponseIds]);

  // Handle click outside to close dropdown
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        isFilterDropdownOpen &&
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node) &&
        !inputRef.current?.contains(event.target as Node)
      ) {
        setIsFilterDropdownOpen(false);
        setFilterSearchTerm("");
        setSelectedFilterIndex(0);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isFilterDropdownOpen]);

  const { data: nudges = [], cancel: cancelNudges } = useGetNudgesQuery(
    previousResponseIds[endpoint]
  );

  const handleSSEStream = async (userMessage: Message) => {
    const apiEndpoint = endpoint === "chat" ? "/api/chat" : "/api/langflow";

    try {
      // Abort any existing stream before starting a new one
      if (streamAbortRef.current) {
        streamAbortRef.current.abort();
      }
      const controller = new AbortController();
      streamAbortRef.current = controller;
      const thisStreamId = ++streamIdRef.current;
      const requestBody: RequestBody = {
        prompt: userMessage.content,
        stream: true,
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
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
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

      // Initialize streaming message
      if (!controller.signal.aborted && thisStreamId === streamIdRef.current) {
        setStreamingMessage({
          content: "",
          functionCalls: [],
          timestamp: new Date(),
        });
      }

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (controller.signal.aborted || thisStreamId !== streamIdRef.current)
            break;
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // Process complete lines (JSON objects)
          const lines = buffer.split("\n");
          buffer = lines.pop() || ""; // Keep incomplete line in buffer

          for (const line of lines) {
            if (line.trim()) {
              try {
                const chunk = JSON.parse(line);
                console.log(
                  "Received chunk:",
                  chunk.type || chunk.object,
                  chunk
                );

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
                    console.log(
                      "Function call in delta:",
                      chunk.delta.function_call
                    );

                    // Check if this is a new function call
                    if (chunk.delta.function_call.name) {
                      console.log(
                        "New function call:",
                        chunk.delta.function_call.name
                      );
                      const functionCall: FunctionCall = {
                        name: chunk.delta.function_call.name,
                        arguments: undefined,
                        status: "pending",
                        argumentsString:
                          chunk.delta.function_call.arguments || "",
                      };
                      currentFunctionCalls.push(functionCall);
                      console.log("Added function call:", functionCall);
                    }
                    // Or if this is arguments continuation
                    else if (chunk.delta.function_call.arguments) {
                      console.log(
                        "Function call arguments delta:",
                        chunk.delta.function_call.arguments
                      );
                      const lastFunctionCall =
                        currentFunctionCalls[currentFunctionCalls.length - 1];
                      if (lastFunctionCall) {
                        if (!lastFunctionCall.argumentsString) {
                          lastFunctionCall.argumentsString = "";
                        }
                        lastFunctionCall.argumentsString +=
                          chunk.delta.function_call.arguments;
                        console.log(
                          "Accumulated arguments:",
                          lastFunctionCall.argumentsString
                        );

                        // Try to parse arguments if they look complete
                        if (lastFunctionCall.argumentsString.includes("}")) {
                          try {
                            const parsed = JSON.parse(
                              lastFunctionCall.argumentsString
                            );
                            lastFunctionCall.arguments = parsed;
                            lastFunctionCall.status = "completed";
                            console.log("Parsed function arguments:", parsed);
                          } catch (e) {
                            console.log(
                              "Arguments not yet complete or invalid JSON:",
                              e
                            );
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
                    console.log("Tool calls in delta:", chunk.delta.tool_calls);

                    for (const toolCall of chunk.delta.tool_calls) {
                      if (toolCall.function) {
                        // Check if this is a new tool call
                        if (toolCall.function.name) {
                          console.log("New tool call:", toolCall.function.name);
                          const functionCall: FunctionCall = {
                            name: toolCall.function.name,
                            arguments: undefined,
                            status: "pending",
                            argumentsString: toolCall.function.arguments || "",
                          };
                          currentFunctionCalls.push(functionCall);
                          console.log("Added tool call:", functionCall);
                        }
                        // Or if this is arguments continuation
                        else if (toolCall.function.arguments) {
                          console.log(
                            "Tool call arguments delta:",
                            toolCall.function.arguments
                          );
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
                            console.log(
                              "Accumulated tool arguments:",
                              lastFunctionCall.argumentsString
                            );

                            // Try to parse arguments if they look complete
                            if (
                              lastFunctionCall.argumentsString.includes("}")
                            ) {
                              try {
                                const parsed = JSON.parse(
                                  lastFunctionCall.argumentsString
                                );
                                lastFunctionCall.arguments = parsed;
                                lastFunctionCall.status = "completed";
                                console.log("Parsed tool arguments:", parsed);
                              } catch (e) {
                                console.log(
                                  "Tool arguments not yet complete or invalid JSON:",
                                  e
                                );
                              }
                            }
                          }
                        }
                      }
                    }
                  }

                  // Handle content/text in delta
                  else if (chunk.delta.content) {
                    console.log("Content delta:", chunk.delta.content);
                    currentContent += chunk.delta.content;
                  }

                  // Handle finish reason
                  if (chunk.delta.finish_reason) {
                    console.log("Finish reason:", chunk.delta.finish_reason);
                    // Mark any pending function calls as completed
                    currentFunctionCalls.forEach((fc) => {
                      if (fc.status === "pending" && fc.argumentsString) {
                        try {
                          fc.arguments = JSON.parse(fc.argumentsString);
                          fc.status = "completed";
                          console.log("Completed function call on finish:", fc);
                        } catch (e) {
                          fc.arguments = { raw: fc.argumentsString };
                          fc.status = "error";
                          console.log(
                            "Error parsing function call on finish:",
                            fc,
                            e
                          );
                        }
                      }
                    });
                  }
                }

                // Handle Realtime API format (this is what you're actually getting!)
                else if (
                  chunk.type === "response.output_item.added" &&
                  chunk.item?.type === "function_call"
                ) {
                  console.log(
                    "🟢 CREATING function call (added):",
                    chunk.item.id,
                    chunk.item.tool_name || chunk.item.name
                  );

                  // Try to find an existing pending call to update (created by earlier deltas)
                  let existing = currentFunctionCalls.find(
                    (fc) => fc.id === chunk.item.id
                  );
                  if (!existing) {
                    existing = [...currentFunctionCalls]
                      .reverse()
                      .find(
                        (fc) =>
                          fc.status === "pending" &&
                          !fc.id &&
                          fc.name === (chunk.item.tool_name || chunk.item.name)
                      );
                  }

                  if (existing) {
                    existing.id = chunk.item.id;
                    existing.type = chunk.item.type;
                    existing.name =
                      chunk.item.tool_name || chunk.item.name || existing.name;
                    existing.arguments =
                      chunk.item.inputs || existing.arguments;
                    console.log(
                      "🟢 UPDATED existing pending function call with id:",
                      existing.id
                    );
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
                    console.log(
                      "🟢 Function calls now:",
                      currentFunctionCalls.map((fc) => ({
                        id: fc.id,
                        name: fc.name,
                      }))
                    );
                  }
                }

                // Handle function call arguments streaming (Realtime API)
                else if (
                  chunk.type === "response.function_call_arguments.delta"
                ) {
                  console.log(
                    "Function args delta (Realtime API):",
                    chunk.delta
                  );
                  const lastFunctionCall =
                    currentFunctionCalls[currentFunctionCalls.length - 1];
                  if (lastFunctionCall) {
                    if (!lastFunctionCall.argumentsString) {
                      lastFunctionCall.argumentsString = "";
                    }
                    lastFunctionCall.argumentsString += chunk.delta || "";
                    console.log(
                      "Accumulated arguments (Realtime API):",
                      lastFunctionCall.argumentsString
                    );
                  }
                }

                // Handle function call arguments completion (Realtime API)
                else if (
                  chunk.type === "response.function_call_arguments.done"
                ) {
                  console.log(
                    "Function args done (Realtime API):",
                    chunk.arguments
                  );
                  const lastFunctionCall =
                    currentFunctionCalls[currentFunctionCalls.length - 1];
                  if (lastFunctionCall) {
                    try {
                      lastFunctionCall.arguments = JSON.parse(
                        chunk.arguments || "{}"
                      );
                      lastFunctionCall.status = "completed";
                      console.log(
                        "Parsed function arguments (Realtime API):",
                        lastFunctionCall.arguments
                      );
                    } catch (e) {
                      lastFunctionCall.arguments = { raw: chunk.arguments };
                      lastFunctionCall.status = "error";
                      console.log(
                        "Error parsing function arguments (Realtime API):",
                        e
                      );
                    }
                  }
                }

                // Handle function call completion (Realtime API)
                else if (
                  chunk.type === "response.output_item.done" &&
                  chunk.item?.type === "function_call"
                ) {
                  console.log(
                    "🔵 UPDATING function call (done):",
                    chunk.item.id,
                    chunk.item.tool_name || chunk.item.name
                  );
                  console.log(
                    "🔵 Looking for existing function calls:",
                    currentFunctionCalls.map((fc) => ({
                      id: fc.id,
                      name: fc.name,
                    }))
                  );

                  // Find existing function call by ID or name
                  const functionCall = currentFunctionCalls.find(
                    (fc) =>
                      fc.id === chunk.item.id ||
                      fc.name === chunk.item.tool_name ||
                      fc.name === chunk.item.name
                  );

                  if (functionCall) {
                    console.log(
                      "🔵 FOUND existing function call, updating:",
                      functionCall.id,
                      functionCall.name
                    );
                    // Update existing function call with completion data
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

                    // Set results if present
                    if (chunk.item.results) {
                      functionCall.result = chunk.item.results;
                    }
                  } else {
                    console.log(
                      "🔴 WARNING: Could not find existing function call to update:",
                      chunk.item.id,
                      chunk.item.tool_name,
                      chunk.item.name
                    );
                  }
                }

                // Handle tool call completion with results
                else if (
                  chunk.type === "response.output_item.done" &&
                  chunk.item?.type?.includes("_call") &&
                  chunk.item?.type !== "function_call"
                ) {
                  console.log("Tool call done with results:", chunk.item);

                  // Find existing function call by ID, or by name/type if ID not available
                  const functionCall = currentFunctionCalls.find(
                    (fc) =>
                      fc.id === chunk.item.id ||
                      fc.name === chunk.item.tool_name ||
                      fc.name === chunk.item.name ||
                      fc.name === chunk.item.type ||
                      fc.name.includes(chunk.item.type.replace("_call", "")) ||
                      chunk.item.type.includes(fc.name)
                  );

                  if (functionCall) {
                    // Update existing function call
                    functionCall.arguments =
                      chunk.item.inputs || functionCall.arguments;
                    functionCall.status =
                      chunk.item.status === "completed" ? "completed" : "error";
                    functionCall.id = chunk.item.id;
                    functionCall.type = chunk.item.type;

                    // Set the results
                    if (chunk.item.results) {
                      functionCall.result = chunk.item.results;
                    }
                  } else {
                    // Create new function call if not found
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

                // Handle function call output item added (new format)
                else if (
                  chunk.type === "response.output_item.added" &&
                  chunk.item?.type?.includes("_call") &&
                  chunk.item?.type !== "function_call"
                ) {
                  console.log(
                    "🟡 CREATING tool call (added):",
                    chunk.item.id,
                    chunk.item.tool_name || chunk.item.name,
                    chunk.item.type
                  );

                  // Dedupe by id or pending with same name
                  let existing = currentFunctionCalls.find(
                    (fc) => fc.id === chunk.item.id
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
                              chunk.item.type)
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
                    console.log(
                      "🟡 UPDATED existing pending tool call with id:",
                      existing.id
                    );
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
                    console.log(
                      "🟡 Function calls now:",
                      currentFunctionCalls.map((fc) => ({
                        id: fc.id,
                        name: fc.name,
                        type: fc.type,
                      }))
                    );
                  }
                }

                // Handle function call results
                else if (
                  chunk.type === "response.function_call.result" ||
                  chunk.type === "function_call_result"
                ) {
                  console.log("Function call result:", chunk.result || chunk);
                  const lastFunctionCall =
                    currentFunctionCalls[currentFunctionCalls.length - 1];
                  if (lastFunctionCall) {
                    lastFunctionCall.result =
                      chunk.result || chunk.output || chunk.response;
                    lastFunctionCall.status = "completed";
                  }
                }

                // Handle tool call results
                else if (
                  chunk.type === "response.tool_call.result" ||
                  chunk.type === "tool_call_result"
                ) {
                  console.log("Tool call result:", chunk.result || chunk);
                  const lastFunctionCall =
                    currentFunctionCalls[currentFunctionCalls.length - 1];
                  if (lastFunctionCall) {
                    lastFunctionCall.result =
                      chunk.result || chunk.output || chunk.response;
                    lastFunctionCall.status = "completed";
                  }
                }

                // Handle generic results that might be in different formats
                else if (
                  (chunk.type && chunk.type.includes("result")) ||
                  chunk.result
                ) {
                  console.log("Generic result:", chunk);
                  const lastFunctionCall =
                    currentFunctionCalls[currentFunctionCalls.length - 1];
                  if (lastFunctionCall && !lastFunctionCall.result) {
                    lastFunctionCall.result =
                      chunk.result || chunk.output || chunk.response || chunk;
                    lastFunctionCall.status = "completed";
                  }
                }

                // Handle text output streaming (Realtime API)
                else if (chunk.type === "response.output_text.delta") {
                  console.log("Text delta (Realtime API):", chunk.delta);
                  currentContent += chunk.delta || "";
                }

                // Log unhandled chunks
                else if (
                  chunk.type !== null &&
                  chunk.object !== "response.chunk"
                ) {
                  console.log("Unhandled chunk format:", chunk);
                }

                // Update streaming message
                if (
                  !controller.signal.aborted &&
                  thisStreamId === streamIdRef.current
                ) {
                  setStreamingMessage({
                    content: currentContent,
                    functionCalls: [...currentFunctionCalls],
                    timestamp: new Date(),
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
      }

      // Finalize the message
      const finalMessage: Message = {
        role: "assistant",
        content: currentContent,
        functionCalls: currentFunctionCalls,
        timestamp: new Date(),
      };

      if (!controller.signal.aborted && thisStreamId === streamIdRef.current) {
        setMessages((prev) => [...prev, finalMessage]);
        setStreamingMessage(null);
        if (previousResponseIds[endpoint]) {
          cancelNudges();
        }
      }

      // Store the response ID for the next request for this endpoint
      if (
        newResponseId &&
        !controller.signal.aborted &&
        thisStreamId === streamIdRef.current
      ) {
        setPreviousResponseIds((prev) => ({
          ...prev,
          [endpoint]: newResponseId,
        }));

        // If this is a new conversation (no currentConversationId), set it now
        if (!currentConversationId) {
          setCurrentConversationId(newResponseId);
          refreshConversations(true);
        } else {
          // For existing conversations, do a silent refresh to keep backend in sync
          refreshConversationsSilent();
        }
      }
    } catch (error) {
      // If stream was aborted (e.g., starting new conversation), do not append errors or final messages
      if (streamAbortRef.current?.signal.aborted) {
        return;
      }
      console.error("SSE Stream error:", error);
      setStreamingMessage(null);

      const errorMessage: Message = {
        role: "assistant",
        content:
          "Sorry, I couldn't connect to the chat service. Please try again.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    }
  };

  const handleSendMessage = async (inputMessage: string) => {
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

    if (asyncMode) {
      await handleSSEStream(userMessage);
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
    handleSendMessage(input);
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
    event?: React.MouseEvent
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

  const renderFunctionCalls = (
    functionCalls: FunctionCall[],
    messageIndex?: number
  ) => {
    if (!functionCalls || functionCalls.length === 0) return null;

    return (
      <div className="mb-3 space-y-2">
        {functionCalls.map((fc, index) => {
          const functionCallId = `${messageIndex || "streaming"}-${index}`;
          const isExpanded = expandedFunctionCalls.has(functionCallId);

          // Determine display name - show both name and type if available
          const displayName =
            fc.type && fc.type !== fc.name
              ? `${fc.name} (${fc.type})`
              : fc.name;

          return (
            <div
              key={index}
              className="rounded-lg bg-blue-500/10 border border-blue-500/20 p-3"
            >
              <div
                className="flex items-center gap-2 cursor-pointer hover:bg-blue-500/5 -m-3 p-3 rounded-lg transition-colors"
                onClick={() => toggleFunctionCall(functionCallId)}
              >
                <Settings className="h-4 w-4 text-blue-400" />
                <span className="text-sm font-medium text-blue-400 flex-1">
                  Function Call: {displayName}
                </span>
                {fc.id && (
                  <span className="text-xs text-blue-300/70 font-mono">
                    {fc.id.substring(0, 8)}...
                  </span>
                )}
                <div
                  className={`px-2 py-1 rounded text-xs font-medium ${
                    fc.status === "completed"
                      ? "bg-green-500/20 text-green-400"
                      : fc.status === "error"
                      ? "bg-red-500/20 text-red-400"
                      : "bg-yellow-500/20 text-yellow-400"
                  }`}
                >
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
                  {/* Show type information if available */}
                  {fc.type && (
                    <div className="text-xs text-muted-foreground mb-3">
                      <span className="font-medium">Type:</span>
                      <span className="ml-2 px-2 py-1 bg-muted/30 rounded font-mono">
                        {fc.type}
                      </span>
                    </div>
                  )}

                  {/* Show ID if available */}
                  {fc.id && (
                    <div className="text-xs text-muted-foreground mb-3">
                      <span className="font-medium">ID:</span>
                      <span className="ml-2 px-2 py-1 bg-muted/30 rounded font-mono">
                        {fc.id}
                      </span>
                    </div>
                  )}

                  {/* Show arguments - either completed or streaming */}
                  {(fc.arguments || fc.argumentsString) && (
                    <div className="text-xs text-muted-foreground mb-3">
                      <span className="font-medium">Arguments:</span>
                      <pre className="mt-1 p-2 bg-muted/30 rounded text-xs overflow-x-auto">
                        {fc.arguments
                          ? JSON.stringify(fc.arguments, null, 2)
                          : fc.argumentsString || "..."}
                      </pre>
                    </div>
                  )}

                  {fc.result && (
                    <div className="text-xs text-muted-foreground">
                      <span className="font-medium">Result:</span>
                      {Array.isArray(fc.result) ? (
                        <div className="mt-1 space-y-2">
                          {(() => {
                            // Handle different result formats
                            let resultsToRender = fc.result;

                            // Check if this is function_call format with nested results
                            // Function call format: results = [{ results: [...] }]
                            // Tool call format: results = [{ text_key: ..., data: {...} }]
                            if (
                              fc.result.length > 0 &&
                              fc.result[0]?.results &&
                              Array.isArray(fc.result[0].results) &&
                              !fc.result[0].text_key
                            ) {
                              resultsToRender = fc.result[0].results;
                            }

                            type ToolResultItem = {
                              text_key?: string;
                              data?: { file_path?: string; text?: string };
                              filename?: string;
                              page?: number;
                              score?: number;
                              source_url?: string | null;
                              text?: string;
                            };
                            const items =
                              resultsToRender as unknown as ToolResultItem[];
                            return items.map((result, idx: number) => (
                              <div
                                key={idx}
                                className="p-2 bg-muted/30 rounded border border-muted/50"
                              >
                                {/* Handle tool_call format (file_path in data) */}
                                {result.data?.file_path && (
                                  <div className="font-medium text-blue-400 mb-1 text-xs">
                                    📄 {result.data.file_path || "Unknown file"}
                                  </div>
                                )}

                                {/* Handle function_call format (filename directly) */}
                                {result.filename && !result.data?.file_path && (
                                  <div className="font-medium text-blue-400 mb-1 text-xs">
                                    📄 {result.filename}
                                    {result.page && ` (page ${result.page})`}
                                    {result.score && (
                                      <span className="ml-2 text-xs text-muted-foreground">
                                        Score: {result.score.toFixed(3)}
                                      </span>
                                    )}
                                  </div>
                                )}

                                {/* Handle tool_call text format */}
                                {result.data?.text && (
                                  <div className="text-xs text-foreground whitespace-pre-wrap max-h-32 overflow-y-auto">
                                    {result.data.text.length > 300
                                      ? result.data.text.substring(0, 300) +
                                        "..."
                                      : result.data.text}
                                  </div>
                                )}

                                {/* Handle function_call text format */}
                                {result.text && !result.data?.text && (
                                  <div className="text-xs text-foreground whitespace-pre-wrap max-h-32 overflow-y-auto">
                                    {result.text.length > 300
                                      ? result.text.substring(0, 300) + "..."
                                      : result.text}
                                  </div>
                                )}

                                {/* Show additional metadata for function_call format */}
                                {result.source_url && (
                                  <div className="text-xs text-muted-foreground mt-1">
                                    <a
                                      href={result.source_url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="text-blue-400 hover:underline"
                                    >
                                      Source URL
                                    </a>
                                  </div>
                                )}

                                {result.text_key && (
                                  <div className="text-xs text-muted-foreground mt-1">
                                    Key: {result.text_key}
                                  </div>
                                )}
                              </div>
                            ));
                          })()}
                          <div className="text-xs text-muted-foreground">
                            Found{" "}
                            {(() => {
                              let resultsToCount = fc.result;
                              if (
                                fc.result.length > 0 &&
                                fc.result[0]?.results &&
                                Array.isArray(fc.result[0].results) &&
                                !fc.result[0].text_key
                              ) {
                                resultsToCount = fc.result[0].results;
                              }
                              return resultsToCount.length;
                            })()}{" "}
                            result
                            {(() => {
                              let resultsToCount = fc.result;
                              if (
                                fc.result.length > 0 &&
                                fc.result[0]?.results &&
                                Array.isArray(fc.result[0].results) &&
                                !fc.result[0].text_key
                              ) {
                                resultsToCount = fc.result[0].results;
                              }
                              return resultsToCount.length !== 1 ? "s" : "";
                            })()}
                          </div>
                        </div>
                      ) : (
                        <pre className="mt-1 p-2 bg-muted/30 rounded text-xs overflow-x-auto">
                          {JSON.stringify(fc.result, null, 2)}
                        </pre>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  const handleSuggestionClick = (suggestion: string) => {
    handleSendMessage(suggestion);
  };

  return (
    <div
      className={`fixed inset-0 md:left-72 top-[53px] flex flex-col transition-all duration-300 ${
        isMenuOpen && isPanelOpen
          ? "md:right-[704px]" // Both open: 384px (menu) + 320px (KF panel)
          : isMenuOpen
          ? "md:right-96" // Only menu open: 384px
          : isPanelOpen
          ? "md:right-80" // Only KF panel open: 320px
          : "md:right-6" // Neither open: 24px
      }`}
    >
      {/* Debug header - only show in debug mode */}
      {isDebugMode && (
        <div className="flex items-center justify-between mb-6 px-6 pt-6">
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

      <div
        className={`flex-1 flex flex-col min-h-0 px-6 ${
          !isDebugMode ? "pt-6" : ""
        }`}
      >
        <div className="flex-1 flex flex-col gap-4 min-h-0 overflow-hidden">
          {/* Messages Area */}
          <div
            className={`flex-1 overflow-y-auto overflow-x-hidden scrollbar-hide space-y-6 min-h-0 transition-all relative ${
              isDragOver
                ? "bg-primary/10 border-2 border-dashed border-primary rounded-lg p-4"
                : ""
            }`}
            onDragEnter={handleDragEnter}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            {messages.length === 0 && !streamingMessage ? (
              <div className="flex items-center justify-center h-full text-muted-foreground">
                <div className="text-center">
                  {isDragOver ? (
                    <>
                      <Upload className="h-12 w-12 mx-auto mb-4 text-primary" />
                      <p className="text-primary font-medium">
                        Drop your document here
                      </p>
                      <p className="text-sm mt-2">
                        I&apos;ll process it and add it to our conversation
                        context
                      </p>
                    </>
                  ) : isUploading ? (
                    <>
                      <Loader2 className="h-12 w-12 mx-auto mb-4 animate-spin" />
                      <p>Processing your document...</p>
                      <p className="text-sm mt-2">
                        This may take a few moments
                      </p>
                    </>
                  ) : null}
                </div>
              </div>
            ) : (
              <>
                {messages.map((message, index) => (
                  <div key={index} className="space-y-6 group">
                    {message.role === "user" && (
                      <div className="flex gap-3">
                        <Avatar className="w-8 h-8 flex-shrink-0">
                          <AvatarImage src={user?.picture} alt={user?.name} />
                          <AvatarFallback className="text-sm bg-primary/20 text-primary">
                            {user?.name ? (
                              user.name.charAt(0).toUpperCase()
                            ) : (
                              <User className="h-4 w-4" />
                            )}
                          </AvatarFallback>
                        </Avatar>
                        <div className="flex-1">
                          <p className="text-foreground whitespace-pre-wrap break-words overflow-wrap-anywhere">
                            {message.content}
                          </p>
                        </div>
                      </div>
                    )}

                    {message.role === "assistant" && (
                      <div className="flex gap-3">
                        <div className="w-8 h-8 rounded-lg bg-accent/20 flex items-center justify-center flex-shrink-0">
                          <Bot className="h-4 w-4 text-accent-foreground" />
                        </div>
                        <div className="flex-1 min-w-0">
                          {renderFunctionCalls(
                            message.functionCalls || [],
                            index
                          )}
                          <MarkdownRenderer chatMessage={message.content} />
                        </div>
                        {endpoint === "chat" && (
                          <div className="flex-shrink-0 ml-2">
                            <button
                              onClick={(e) => handleForkConversation(index, e)}
                              className="opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-accent rounded text-muted-foreground hover:text-foreground"
                              title="Fork conversation from here"
                            >
                              <GitBranch className="h-3 w-3" />
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}

                {/* Streaming Message Display */}
                {streamingMessage && (
                  <div className="flex gap-3">
                    <div className="w-8 h-8 rounded-lg bg-accent/20 flex items-center justify-center flex-shrink-0">
                      <Bot className="h-4 w-4 text-accent-foreground" />
                    </div>
                    <div className="flex-1">
                      {renderFunctionCalls(
                        streamingMessage.functionCalls,
                        messages.length
                      )}
                      <MarkdownRenderer
                        chatMessage={streamingMessage.content}
                      />
                      <span className="inline-block w-2 h-4 bg-blue-400 ml-1 animate-pulse"></span>
                    </div>
                  </div>
                )}

                {/* Loading animation - shows immediately after user submits */}
                {loading && (
                  <div className="flex gap-3">
                    <div className="w-8 h-8 rounded-lg bg-accent/20 flex items-center justify-center flex-shrink-0">
                      <Bot className="h-4 w-4 text-accent-foreground" />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                        <span className="text-sm text-muted-foreground">
                          Thinking...
                        </span>
                      </div>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </>
            )}

            {/* Drag overlay for existing messages */}
            {isDragOver && messages.length > 0 && (
              <div className="absolute inset-0 bg-primary/20 backdrop-blur-sm flex items-center justify-center rounded-lg">
                <div className="text-center">
                  <Upload className="h-8 w-8 mx-auto mb-2 text-primary" />
                  <p className="text-primary font-medium">
                    Drop document to add context
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Suggestion chips - always show unless streaming */}
      {!streamingMessage && (
        <Nudges
          nudges={loading ? [] : (nudges as string[])}
          handleSuggestionClick={handleSuggestionClick}
        />
      )}

      {/* Input Area - Fixed at bottom */}
      <div className="flex-shrink-0 p-6 pb-8 pt-4 flex justify-center">
        <div className="w-full max-w-[75%]">
          <form onSubmit={handleSubmit} className="relative">
            <div className="relative w-full bg-muted/20 rounded-lg border border-border/50 focus-within:ring-1 focus-within:ring-ring">
              {selectedFilter && (
                <div className="flex items-center gap-2 px-4 pt-3 pb-1">
                  <span
                    className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium transition-colors ${
                      filterAccentClasses[parsedFilterData?.color || ""]
                    }`}
                  >
                    @filter:{selectedFilter.name}
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedFilter(null);
                        setIsFilterHighlighted(false);
                      }}
                      className="ml-1 rounded-full p-0.5"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                </div>
              )}
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => {
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
                }}
                onKeyDown={(e) => {
                  // Handle backspace for filter clearing
                  if (
                    e.key === "Backspace" &&
                    selectedFilter &&
                    input.trim() === ""
                  ) {
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
                      filter.name
                        .toLowerCase()
                        .includes(filterSearchTerm.toLowerCase())
                    );

                    if (e.key === "Escape") {
                      e.preventDefault();
                      setIsFilterDropdownOpen(false);
                      setFilterSearchTerm("");
                      setSelectedFilterIndex(0);
                      setDropdownDismissed(true);

                      // Keep focus on the textarea so user can continue typing normally
                      inputRef.current?.focus();
                      return;
                    }

                    if (e.key === "ArrowDown") {
                      e.preventDefault();
                      setSelectedFilterIndex((prev) =>
                        prev < filteredFilters.length - 1 ? prev + 1 : 0
                      );
                      return;
                    }

                    if (e.key === "ArrowUp") {
                      e.preventDefault();
                      setSelectedFilterIndex((prev) =>
                        prev > 0 ? prev - 1 : filteredFilters.length - 1
                      );
                      return;
                    }

                    if (e.key === "Enter") {
                      // Check if we're at the end of an @ mention (space before cursor or end of input)
                      const cursorPos = e.currentTarget.selectionStart || 0;
                      const textBeforeCursor = input.slice(0, cursorPos);
                      const words = textBeforeCursor.split(" ");
                      const lastWord = words[words.length - 1];

                      if (
                        lastWord.startsWith("@") &&
                        filteredFilters[selectedFilterIndex]
                      ) {
                        e.preventDefault();
                        handleFilterSelect(
                          filteredFilters[selectedFilterIndex]
                        );
                        return;
                      }
                    }

                    if (e.key === " ") {
                      // Select filter on space if we're typing an @ mention
                      const cursorPos = e.currentTarget.selectionStart || 0;
                      const textBeforeCursor = input.slice(0, cursorPos);
                      const words = textBeforeCursor.split(" ");
                      const lastWord = words[words.length - 1];

                      if (
                        lastWord.startsWith("@") &&
                        filteredFilters[selectedFilterIndex]
                      ) {
                        e.preventDefault();
                        handleFilterSelect(
                          filteredFilters[selectedFilterIndex]
                        );
                        return;
                      }
                    }
                  }

                  if (
                    e.key === "Enter" &&
                    !e.shiftKey &&
                    !isFilterDropdownOpen
                  ) {
                    e.preventDefault();
                    if (input.trim() && !loading) {
                      // Trigger form submission by finding the form and calling submit
                      const form = e.currentTarget.closest("form");
                      if (form) {
                        form.requestSubmit();
                      }
                    }
                  }
                }}
                placeholder="Type to ask a question..."
                disabled={loading}
                className={`w-full bg-transparent px-4 ${
                  selectedFilter ? "py-2 pb-4" : "py-4"
                } min-h-[100px] focus-visible:outline-none resize-none`}
                rows={1}
              />
            </div>
            <input
              ref={fileInputRef}
              type="file"
              onChange={handleFilePickerChange}
              className="hidden"
              accept=".pdf,.doc,.docx,.txt,.md,.rtf,.odt"
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={handleFilterDropdownToggle}
              className="absolute bottom-3 left-3 h-8 w-8 p-0 rounded-full hover:bg-muted/50"
            >
              <AtSign className="h-4 w-4" />
            </Button>
            {isFilterDropdownOpen && (
              <div
                ref={dropdownRef}
                className="absolute bottom-14 left-0 w-64 bg-popover border border-border rounded-md shadow-md z-50 p-2"
              >
                <div className="space-y-1">
                  {filterSearchTerm && (
                    <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground">
                      Searching: @{filterSearchTerm}
                    </div>
                  )}
                  {availableFilters.length === 0 ? (
                    <div className="px-2 py-3 text-sm text-muted-foreground">
                      No knowledge filters available
                    </div>
                  ) : (
                    <>
                      {!filterSearchTerm && (
                        <button
                          onClick={() => handleFilterSelect(null)}
                          className={`w-full text-left px-2 py-2 text-sm rounded hover:bg-muted/50 flex items-center justify-between ${
                            selectedFilterIndex === -1 ? "bg-muted/50" : ""
                          }`}
                        >
                          <span>No filter</span>
                          {!selectedFilter && (
                            <div className="w-2 h-2 rounded-full bg-blue-500" />
                          )}
                        </button>
                      )}
                      {availableFilters
                        .filter((filter) =>
                          filter.name
                            .toLowerCase()
                            .includes(filterSearchTerm.toLowerCase())
                        )
                        .map((filter, index) => (
                          <button
                            key={filter.id}
                            onClick={() => handleFilterSelect(filter)}
                            className={`w-full text-left px-2 py-2 text-sm rounded hover:bg-muted/50 flex items-center justify-between ${
                              index === selectedFilterIndex ? "bg-muted/50" : ""
                            }`}
                          >
                            <div>
                              <div className="font-medium">{filter.name}</div>
                              {filter.description && (
                                <div className="text-xs text-muted-foreground truncate">
                                  {filter.description}
                                </div>
                              )}
                            </div>
                            {selectedFilter?.id === filter.id && (
                              <div className="w-2 h-2 rounded-full bg-blue-500" />
                            )}
                          </button>
                        ))}
                      {availableFilters.filter((filter) =>
                        filter.name
                          .toLowerCase()
                          .includes(filterSearchTerm.toLowerCase())
                      ).length === 0 &&
                        filterSearchTerm && (
                          <div className="px-2 py-3 text-sm text-muted-foreground">
                            No filters match &quot;{filterSearchTerm}&quot;
                          </div>
                        )}
                    </>
                  )}
                </div>
              </div>
            )}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={handleFilePickerClick}
              disabled={isUploading}
              className="absolute bottom-3 left-12 h-8 w-8 p-0 rounded-full hover:bg-muted/50"
            >
              <Plus className="h-4 w-4" />
            </Button>
            <Button
              type="submit"
              disabled={!input.trim() || loading}
              className="absolute bottom-3 right-3 rounded-lg h-10 px-4"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Send"}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default function ProtectedChatPage() {
  return (
    <ProtectedRoute>
      <ChatPage />
    </ProtectedRoute>
  );
}
