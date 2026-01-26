"use client";

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";

export type EndpointType = "chat" | "langflow";

interface ConversationDocument {
  filename: string;
  uploadTime: Date;
}

interface ConversationMessage {
  role: string;
  content: string;
  timestamp?: string;
  response_id?: string;
}

interface KnowledgeFilter {
  id: string;
  name: string;
  description: string;
  query_data: string;
  owner: string;
  created_at: string;
  updated_at: string;
}

interface ConversationData {
  messages: ConversationMessage[];
  endpoint: EndpointType;
  response_id: string;
  title: string;
  filter?: KnowledgeFilter | null;
  [key: string]: unknown;
}

interface ChatContextType {
  endpoint: EndpointType;
  setEndpoint: (endpoint: EndpointType) => void;
  currentConversationId: string | null;
  setCurrentConversationId: (id: string | null) => void;
  previousResponseIds: {
    chat: string | null;
    langflow: string | null;
  };
  setPreviousResponseIds: (
    ids:
      | { chat: string | null; langflow: string | null }
      | ((prev: { chat: string | null; langflow: string | null }) => {
          chat: string | null;
          langflow: string | null;
        }),
  ) => void;
  refreshConversations: (force?: boolean) => void;
  refreshConversationsSilent: () => Promise<void>;
  refreshTrigger: number;
  refreshTriggerSilent: number;
  loadConversation: (conversation: ConversationData) => Promise<void>;
  startNewConversation: () => void;
  conversationData: ConversationData | null;
  forkFromResponse: (responseId: string) => void;
  conversationDocs: ConversationDocument[];
  addConversationDoc: (filename: string) => void;
  clearConversationDocs: () => void;
  placeholderConversation: ConversationData | null;
  setPlaceholderConversation: (conversation: ConversationData | null) => void;
  conversationLoaded: boolean;
  setConversationLoaded: (loaded: boolean) => void;
  conversationFilter: KnowledgeFilter | null;
  // responseId: undefined = use currentConversationId, null = don't save to localStorage
  setConversationFilter: (filter: KnowledgeFilter | null, responseId?: string | null) => void;
  hasChatError: boolean;
  setChatError: (hasError: boolean) => void;
  isOnboardingComplete: boolean;
  setOnboardingComplete: (complete: boolean) => void;
}

const ChatContext = createContext<ChatContextType | undefined>(undefined);

interface ChatProviderProps {
  children: ReactNode;
}

export function ChatProvider({ children }: ChatProviderProps) {
  const [endpoint, setEndpoint] = useState<EndpointType>("langflow");
  const [currentConversationId, setCurrentConversationId] = useState<
    string | null
  >(null);
  const [previousResponseIds, setPreviousResponseIds] = useState<{
    chat: string | null;
    langflow: string | null;
  }>({ chat: null, langflow: null });
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [refreshTriggerSilent, setRefreshTriggerSilent] = useState(0);
  const [conversationData, setConversationData] =
    useState<ConversationData | null>(null);
  const [conversationDocs, setConversationDocs] = useState<
    ConversationDocument[]
  >([]);
  const [placeholderConversation, setPlaceholderConversation] =
    useState<ConversationData | null>(null);
  const [conversationLoaded, setConversationLoaded] = useState(false);
  const [conversationFilter, setConversationFilterState] =
    useState<KnowledgeFilter | null>(null);
  const [hasChatError, setChatError] = useState(false);
  
  // Get settings to check if onboarding was completed (settings.edited)
  const { data: settings } = useGetSettingsQuery();
  
  // Check if onboarding is complete
  // Onboarding is complete if:
  // 1. settings.edited is true (backend confirms onboarding was completed)
  // 2. AND onboarding step key is null (local onboarding flow is done)
  const [isOnboardingComplete, setIsOnboardingComplete] = useState(() => {
    if (typeof window === "undefined") return false;
    // Default to false if settings not loaded yet
    return false;
  });

  // Sync onboarding completion state with settings from backend
  useEffect(() => {
    const TOTAL_ONBOARDING_STEPS = 4;
    // Onboarding is complete if current_step >= 4
    const isComplete =
      settings?.onboarding?.current_step !== undefined &&
      settings.onboarding.current_step >= TOTAL_ONBOARDING_STEPS;
    setIsOnboardingComplete(isComplete);
  }, [settings?.onboarding?.current_step]);

  const setOnboardingComplete = useCallback((complete: boolean) => {
    setIsOnboardingComplete(complete);
  }, []);

  // Listen for ingestion failures and set chat error flag
  useEffect(() => {
    const handleIngestionFailed = () => {
      setChatError(true);
    };

    window.addEventListener("ingestionFailed", handleIngestionFailed);
    return () => {
      window.removeEventListener("ingestionFailed", handleIngestionFailed);
    };
  }, []);

  // Debounce refresh requests to prevent excessive reloads
  const refreshTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const refreshConversations = useCallback((force = false) => {
    console.log("[REFRESH] refreshConversations called, force:", force);

    if (force) {
      // Immediate refresh for important updates like new conversations
      setRefreshTrigger((prev) => prev + 1);
      return;
    }

    // Clear any existing timeout
    if (refreshTimeoutRef.current) {
      clearTimeout(refreshTimeoutRef.current);
    }

    // Set a new timeout to debounce multiple rapid refresh calls
    refreshTimeoutRef.current = setTimeout(() => {
      setRefreshTrigger((prev) => prev + 1);
    }, 250); // 250ms debounce
  }, []);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (refreshTimeoutRef.current) {
        clearTimeout(refreshTimeoutRef.current);
      }
    };
  }, []);

  // Silent refresh - updates data without loading states
  const refreshConversationsSilent = useCallback(async () => {
    // Trigger silent refresh that updates conversation data without showing loading states
    setRefreshTriggerSilent((prev) => prev + 1);
  }, []);

  const loadConversation = useCallback(
    async (conversation: ConversationData) => {
      console.log("[CONVERSATION] Loading conversation:", {
        conversationId: conversation.response_id,
        title: conversation.title,
        endpoint: conversation.endpoint,
      });

      setCurrentConversationId(conversation.response_id);
      setEndpoint(conversation.endpoint);
      // Store the full conversation data for the chat page to use
      setConversationData(conversation);

      // Load the filter if one exists for this conversation
      // Always update the filter to match the conversation being loaded
      const isDifferentConversation =
        conversation.response_id !== conversationData?.response_id;

      if (isDifferentConversation && typeof window !== "undefined") {
        // Try to load the saved filter from localStorage
        const savedFilterId = localStorage.getItem(`conversation_filter_${conversation.response_id}`);
        console.log("[CONVERSATION] Looking for filter:", {
          conversationId: conversation.response_id,
          savedFilterId,
        });

        if (savedFilterId) {
          // Import getFilterById dynamically to avoid circular dependency
          const { getFilterById } = await import("@/app/api/queries/useGetFilterByIdQuery");
          try {
            const filter = await getFilterById(savedFilterId);

            if (filter) {
              console.log("[CONVERSATION] Loaded filter:", filter.name, filter.id);
              setConversationFilterState(filter);
              // Update conversation data with the loaded filter
              setConversationData((prev) => {
                if (!prev) return prev;
                return { ...prev, filter };
              });
            }
          } catch (error) {
            console.error("[CONVERSATION] Failed to load filter:", error);
            // Filter was deleted, clean up localStorage
            localStorage.removeItem(`conversation_filter_${conversation.response_id}`);
            setConversationFilterState(null);
          }
        } else {
          // No saved filter in localStorage, clear the current filter
          console.log("[CONVERSATION] No filter found for this conversation");
          setConversationFilterState(null);
        }
      }

      // Clear placeholder when loading a real conversation
      setPlaceholderConversation(null);
      setConversationLoaded(true);
      // Clear conversation docs to prevent duplicates when switching conversations
      setConversationDocs([]);
    },
    [conversationData?.response_id],
  );

  const startNewConversation = useCallback(async () => {
    console.log("[CONVERSATION] Starting new conversation");

    // Check if there's existing conversation data - if so, this is a manual "new conversation" action
    // Check state values before clearing them
    const hasExistingConversation = conversationData !== null || placeholderConversation !== null;
    
    // Clear current conversation data and reset state
    setCurrentConversationId(null);
    setPreviousResponseIds({ chat: null, langflow: null });
    setConversationData(null);
    setConversationDocs([]);
    setConversationLoaded(false);

    // Load default filter if available (and clear it after first use)
    if (typeof window !== "undefined") {
      const defaultFilterId = localStorage.getItem("default_conversation_filter_id");
      console.log("[CONVERSATION] Default filter ID:", defaultFilterId);

      if (defaultFilterId) {
        // Clear the default filter now so it's only used once
        localStorage.removeItem("default_conversation_filter_id");
        console.log("[CONVERSATION] Cleared default filter (used once)");

        try {
          const { getFilterById } = await import("@/app/api/queries/useGetFilterByIdQuery");
          const filter = await getFilterById(defaultFilterId);

          if (filter) {
            console.log("[CONVERSATION] Loaded default filter:", filter.name, filter.id);
            setConversationFilterState(filter);
          } else {
            // Default filter was deleted
            setConversationFilterState(null);
          }
        } catch (error) {
          console.error("[CONVERSATION] Failed to load default filter:", error);
          setConversationFilterState(null);
        }
      } else {
        // No default filter in localStorage
        if (hasExistingConversation) {
          // User is manually starting a new conversation - clear the filter
          console.log("[CONVERSATION] Manual new conversation - clearing filter");
          setConversationFilterState(null);
        } else {
          // First time after onboarding - preserve existing filter if set
          // This prevents clearing the filter when startNewConversation is called multiple times during onboarding
          console.log("[CONVERSATION] No default filter set, preserving existing filter if any");
          // Don't clear the filter - it may have been set by storeDefaultFilterForNewConversations
        }
      }
    }

    // Create a temporary placeholder conversation to show in sidebar
    const newPlaceholderConversation: ConversationData = {
      response_id: "new-conversation-" + Date.now(),
      title: "New conversation",
      endpoint: endpoint,
      messages: [
        {
          role: "assistant",
          content: "How can I assist?",
          timestamp: new Date().toISOString(),
        },
      ],
      created_at: new Date().toISOString(),
      last_activity: new Date().toISOString(),
    };

    setPlaceholderConversation(newPlaceholderConversation);
    // Force immediate refresh to ensure sidebar shows correct state
    refreshConversations(true);
  }, [endpoint, refreshConversations, conversationData, placeholderConversation]);

  const addConversationDoc = useCallback((filename: string) => {
    setConversationDocs((prev) => [
      ...prev,
      { filename, uploadTime: new Date() },
    ]);
  }, []);

  const clearConversationDocs = useCallback(() => {
    setConversationDocs([]);
  }, []);

  const forkFromResponse = useCallback(
    (responseId: string) => {
      // Start a new conversation with the messages up to the fork point
      setCurrentConversationId(null); // Clear current conversation to indicate new conversation
      setConversationData(null); // Clear conversation data to prevent reloading
      // Set the response ID that we're forking from as the previous response ID
      setPreviousResponseIds((prev) => ({
        ...prev,
        [endpoint]: responseId,
      }));
      // Clear placeholder when forking
      setPlaceholderConversation(null);
      // The messages are already set by the chat page component before calling this
    },
    [endpoint],
  );

  const setConversationFilter = useCallback(
    (filter: KnowledgeFilter | null, responseId?: string | null) => {
      setConversationFilterState(filter);
      // Update the conversation data to include the filter
      setConversationData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          filter,
        };
      });

      // Determine which conversation ID to use for saving
      // - undefined: use currentConversationId (default behavior)
      // - null: explicitly skip saving to localStorage
      // - string: use the provided responseId
      const targetId = responseId === undefined ? currentConversationId : responseId;

      // Save filter association for the target conversation
      if (typeof window !== "undefined" && targetId) {
        const key = `conversation_filter_${targetId}`;
        if (filter) {
          localStorage.setItem(key, filter.id);
        } else {
          localStorage.removeItem(key);
        }
      }
    },
    [currentConversationId],
  );

  const value = useMemo<ChatContextType>(
    () => ({
      endpoint,
      setEndpoint,
      currentConversationId,
      setCurrentConversationId,
      previousResponseIds,
      setPreviousResponseIds,
      refreshConversations,
      refreshConversationsSilent,
      refreshTrigger,
      refreshTriggerSilent,
      loadConversation,
      startNewConversation,
      conversationData,
      forkFromResponse,
      conversationDocs,
      addConversationDoc,
      clearConversationDocs,
      placeholderConversation,
      setPlaceholderConversation,
      conversationLoaded,
      setConversationLoaded,
      conversationFilter,
      setConversationFilter,
      hasChatError,
      setChatError,
      isOnboardingComplete,
      setOnboardingComplete,
    }),
    [
      endpoint,
      currentConversationId,
      previousResponseIds,
      refreshConversations,
      refreshConversationsSilent,
      refreshTrigger,
      refreshTriggerSilent,
      loadConversation,
      startNewConversation,
      conversationData,
      forkFromResponse,
      conversationDocs,
      addConversationDoc,
      clearConversationDocs,
      placeholderConversation,
      conversationLoaded,
      conversationFilter,
      setConversationFilter,
      hasChatError,
      isOnboardingComplete,
      setOnboardingComplete,
    ],
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat(): ChatContextType {
  const context = useContext(ChatContext);
  if (context === undefined) {
    throw new Error("useChat must be used within a ChatProvider");
  }
  return context;
}
