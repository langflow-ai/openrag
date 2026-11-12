"use client";

import {
  createContext,
  type ReactNode,
  use,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
} from "react";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { useOnboardingState } from "@/hooks/use-onboarding-state";

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
  startNewConversation: (opts?: { showPlaceholder?: boolean }) => void;
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
  setConversationFilter: (
    filter: KnowledgeFilter | null,
    responseId?: string | null,
  ) => void;
  hasChatError: boolean;
  setChatError: (hasError: boolean) => void;
  isOnboardingComplete: boolean;
  setOnboardingComplete: (complete: boolean) => void;
  loading: boolean;
  setLoading: (loading: boolean) => void;
}

const ChatContext = createContext<ChatContextType | undefined>(undefined);

interface ChatProviderProps {
  children: ReactNode;
}

type PreviousResponseIds = {
  chat: string | null;
  langflow: string | null;
};

type ChatProviderState = {
  endpoint: EndpointType;
  currentConversationId: string | null;
  previousResponseIds: PreviousResponseIds;
  refreshTrigger: number;
  refreshTriggerSilent: number;
  conversationData: ConversationData | null;
  conversationDocs: ConversationDocument[];
  placeholderConversation: ConversationData | null;
  conversationLoaded: boolean;
  conversationFilter: KnowledgeFilter | null;
  hasChatError: boolean;
  loading: boolean;
};

type ChatProviderAction =
  | { type: "patch"; patch: Partial<ChatProviderState> }
  | {
      type: "previousResponseIds";
      value:
        | PreviousResponseIds
        | ((previous: PreviousResponseIds) => PreviousResponseIds);
    }
  | { type: "refresh"; silent: boolean }
  | { type: "switchSource"; endpoint: EndpointType }
  | { type: "loadConversation"; conversation: ConversationData }
  | { type: "startNewConversation" }
  | { type: "setConversationFilter"; filter: KnowledgeFilter | null }
  | { type: "addConversationDoc"; filename: string }
  | { type: "showPlaceholder"; conversation: ConversationData }
  | { type: "forkConversation"; endpoint: EndpointType; responseId: string };

const initialChatProviderState: ChatProviderState = {
  endpoint: "langflow",
  currentConversationId: null,
  previousResponseIds: { chat: null, langflow: null },
  refreshTrigger: 0,
  refreshTriggerSilent: 0,
  conversationData: null,
  conversationDocs: [],
  placeholderConversation: null,
  conversationLoaded: false,
  conversationFilter: null,
  hasChatError: false,
  loading: false,
};

function chatProviderReducer(
  state: ChatProviderState,
  action: ChatProviderAction,
): ChatProviderState {
  switch (action.type) {
    case "patch":
      return { ...state, ...action.patch };
    case "previousResponseIds":
      return {
        ...state,
        previousResponseIds:
          typeof action.value === "function"
            ? action.value(state.previousResponseIds)
            : action.value,
      };
    case "refresh":
      return action.silent
        ? { ...state, refreshTriggerSilent: state.refreshTriggerSilent + 1 }
        : { ...state, refreshTrigger: state.refreshTrigger + 1 };
    case "switchSource":
      return {
        ...initialChatProviderState,
        endpoint: action.endpoint,
        refreshTrigger: state.refreshTrigger + 1,
        refreshTriggerSilent: state.refreshTriggerSilent,
      };
    case "loadConversation":
      return {
        ...state,
        endpoint: action.conversation.endpoint,
        currentConversationId: action.conversation.response_id,
        conversationData: action.conversation,
        conversationDocs: [],
        placeholderConversation: null,
        conversationLoaded: true,
      };
    case "startNewConversation":
      return {
        ...state,
        currentConversationId: null,
        previousResponseIds: { chat: null, langflow: null },
        conversationData: null,
        conversationDocs: [],
        conversationLoaded: false,
      };
    case "setConversationFilter":
      return {
        ...state,
        conversationFilter: action.filter,
        conversationData: state.conversationData
          ? { ...state.conversationData, filter: action.filter }
          : null,
      };
    case "addConversationDoc":
      return {
        ...state,
        conversationDocs: [
          ...state.conversationDocs,
          { filename: action.filename, uploadTime: new Date() },
        ],
      };
    case "showPlaceholder":
      return {
        ...state,
        placeholderConversation: action.conversation,
        refreshTrigger: state.refreshTrigger + 1,
      };
    case "forkConversation":
      return {
        ...state,
        currentConversationId: null,
        conversationData: null,
        placeholderConversation: null,
        previousResponseIds: {
          ...state.previousResponseIds,
          [action.endpoint]: action.responseId,
        },
      };
  }
}

export function ChatProvider({ children }: ChatProviderProps) {
  // Langflow stays the default until settings load. The persisted kill switch
  // owns the source selection; the debug endpoint selector can only override
  // the initial, still-loading settings value.
  const [state, dispatch] = useReducer(
    chatProviderReducer,
    initialChatProviderState,
  );
  const {
    endpoint,
    currentConversationId,
    previousResponseIds,
    refreshTrigger,
    refreshTriggerSilent,
    conversationData,
    conversationDocs,
    placeholderConversation,
    conversationLoaded,
    conversationFilter,
    hasChatError,
    loading,
  } = state;
  const endpointChosen = useRef(false);
  const configuredEndpoint = useRef<EndpointType | null>(null);
  const { data: settings } = useGetSettingsQuery();
  const disableChatWithLangflow = settings?.agent?.disable_chat_with_langflow;

  const setEndpoint = useCallback((next: EndpointType) => {
    endpointChosen.current = true;
    dispatch({ type: "patch", patch: { endpoint: next } });
  }, []);

  const setCurrentConversationId = useCallback((id: string | null) => {
    dispatch({ type: "patch", patch: { currentConversationId: id } });
  }, []);
  const setPreviousResponseIds = useCallback(
    (
      value:
        | PreviousResponseIds
        | ((previous: PreviousResponseIds) => PreviousResponseIds),
    ) => dispatch({ type: "previousResponseIds", value }),
    [],
  );
  const setPlaceholderConversation = useCallback(
    (conversation: ConversationData | null) =>
      dispatch({
        type: "patch",
        patch: { placeholderConversation: conversation },
      }),
    [],
  );
  // Refs so startNewConversation can read current values without re-creating
  // the callback every time conversationData or placeholderConversation changes.
  const conversationDataRef = useRef<ConversationData | null>(null);
  conversationDataRef.current = conversationData;
  const placeholderConversationRef = useRef<ConversationData | null>(null);
  placeholderConversationRef.current = placeholderConversation;
  const setConversationLoaded = useCallback((loaded: boolean) => {
    dispatch({ type: "patch", patch: { conversationLoaded: loaded } });
  }, []);
  const setChatError = useCallback((hasError: boolean) => {
    dispatch({ type: "patch", patch: { hasChatError: hasError } });
  }, []);
  const setLoading = useCallback((isLoading: boolean) => {
    dispatch({ type: "patch", patch: { loading: isLoading } });
  }, []);

  const { isOnboardingComplete } = useOnboardingState();

  const setOnboardingComplete = useCallback((_complete: boolean) => {
    // no-op: onboarding completion is now derived from settings via useOnboardingState
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
  }, [setChatError]);

  // Debounce refresh requests to prevent excessive reloads
  const refreshTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const refreshConversations = useCallback((force = false) => {
    if (force) {
      // Immediate refresh for important updates like new conversations
      dispatch({ type: "refresh", silent: false });
      return;
    }

    // Clear any existing timeout
    if (refreshTimeoutRef.current) {
      clearTimeout(refreshTimeoutRef.current);
    }

    // Set a new timeout to debounce multiple rapid refresh calls
    refreshTimeoutRef.current = setTimeout(() => {
      dispatch({ type: "refresh", silent: false });
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
    dispatch({ type: "refresh", silent: true });
  }, []);

  useEffect(() => {
    if (disableChatWithLangflow === undefined) return;

    const nextEndpoint: EndpointType = disableChatWithLangflow
      ? "chat"
      : "langflow";
    const settingsChanged =
      configuredEndpoint.current !== null &&
      configuredEndpoint.current !== nextEndpoint;
    configuredEndpoint.current = nextEndpoint;

    // Preserve a deliberate debug selection made before settings finish
    // loading. Once the persisted toggle changes, it must always win.
    if (endpointChosen.current && !settingsChanged) return;
    endpointChosen.current = false;

    if (endpoint === nextEndpoint) return;

    // A single transition clears source-specific state and forces the matching
    // history query to refetch, avoiding transient mixed-source transcripts.
    dispatch({ type: "switchSource", endpoint: nextEndpoint });
  }, [disableChatWithLangflow, endpoint]);

  const loadConversation = useCallback(
    async (conversation: ConversationData) => {
      endpointChosen.current = true;
      dispatch({ type: "loadConversation", conversation });

      // Load the filter if one exists for this conversation
      // Always update the filter to match the conversation being loaded
      const isDifferentConversation =
        conversation.response_id !== conversationData?.response_id;

      if (isDifferentConversation && typeof window !== "undefined") {
        // Try to load the saved filter from localStorage
        const savedFilterId = localStorage.getItem(
          `conversation_filter_${conversation.response_id}`,
        );

        if (savedFilterId) {
          // Import getFilterById dynamically to avoid circular dependency
          const { getFilterById } = await import(
            "@/app/api/queries/useGetFilterByIdQuery"
          );
          try {
            const filter = await getFilterById(savedFilterId);

            if (filter) {
              dispatch({ type: "setConversationFilter", filter });
            }
          } catch (error) {
            console.error("[CONVERSATION] Failed to load filter:", error);
            // Filter was deleted, clean up localStorage
            localStorage.removeItem(
              `conversation_filter_${conversation.response_id}`,
            );
            dispatch({ type: "patch", patch: { conversationFilter: null } });
          }
        } else {
          dispatch({ type: "patch", patch: { conversationFilter: null } });
        }
      }
    },
    [conversationData?.response_id],
  );

  const startNewConversation = useCallback(
    async (opts?: { showPlaceholder?: boolean }) => {
      const showPlaceholder = opts?.showPlaceholder ?? true;
      // Read current values via refs so this callback doesn't need them as deps.
      const hasExistingConversation =
        conversationDataRef.current !== null ||
        placeholderConversationRef.current !== null;

      // Clear current conversation data and reset state atomically.
      dispatch({ type: "startNewConversation" });

      // Load default filter if available (and clear it after first use)
      if (typeof window !== "undefined") {
        const defaultFilterId = localStorage.getItem(
          "default_conversation_filter_id",
        );

        if (defaultFilterId) {
          // Clear the default filter now so it's only used once
          localStorage.removeItem("default_conversation_filter_id");

          try {
            const { getFilterById } = await import(
              "@/app/api/queries/useGetFilterByIdQuery"
            );
            const filter = await getFilterById(defaultFilterId);

            if (filter) {
              dispatch({
                type: "patch",
                patch: { conversationFilter: filter },
              });
            } else {
              // Default filter was deleted
              dispatch({ type: "patch", patch: { conversationFilter: null } });
            }
          } catch (error) {
            console.error(
              "[CONVERSATION] Failed to load default filter:",
              error,
            );
            dispatch({ type: "patch", patch: { conversationFilter: null } });
          }
        } else {
          // No default filter in localStorage
          if (hasExistingConversation) {
            dispatch({ type: "patch", patch: { conversationFilter: null } });
          } else {
            // Don't clear the filter - it may have been set by storeDefaultFilterForNewConversations
          }
        }
      }

      // Create a temporary placeholder conversation to show in sidebar
      const newPlaceholderConversation: ConversationData = {
        response_id: "new-conversation-" + Date.now(),
        title: "New chat...",
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

      if (showPlaceholder) {
        // Show the placeholder and refresh its sidebar source together.
        dispatch({
          type: "showPlaceholder",
          conversation: newPlaceholderConversation,
        });
      }
      // When showPlaceholder=false (auto-load) we do NOT refresh — the caller
      // already has fresh conversation data and calling refreshConversations here
      // would mutate the query key, re-trigger this effect, and cause an infinite loop.
    },
    [endpoint],
  );

  const addConversationDoc = useCallback((filename: string) => {
    dispatch({ type: "addConversationDoc", filename });
  }, []);

  const clearConversationDocs = useCallback(() => {
    dispatch({ type: "patch", patch: { conversationDocs: [] } });
  }, []);

  const forkFromResponse = useCallback(
    (responseId: string) => {
      // Start a new conversation with the messages up to the fork point.
      dispatch({ type: "forkConversation", endpoint, responseId });
      // The messages are already set by the chat page component before calling this
    },
    [endpoint],
  );

  const setConversationFilter = useCallback(
    (filter: KnowledgeFilter | null, responseId?: string | null) => {
      dispatch({ type: "setConversationFilter", filter });

      // Determine which conversation ID to use for saving
      // - undefined: use currentConversationId (default behavior)
      // - null: explicitly skip saving to localStorage
      // - string: use the provided responseId
      const targetId =
        responseId === undefined ? currentConversationId : responseId;

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
      loading,
      setLoading,
    }),
    [
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
      loading,
      setLoading,
    ],
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat(): ChatContextType {
  const context = use(ChatContext);
  if (context === undefined) {
    throw new Error("useChat must be used within a ChatProvider");
  }
  return context;
}
