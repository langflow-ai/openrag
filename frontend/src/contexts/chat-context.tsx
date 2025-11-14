"use client";

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

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

interface ConversationData {
  messages: ConversationMessage[];
  endpoint: EndpointType;
  response_id: string;
  title: string;
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
  loadConversation: (conversation: ConversationData) => void;
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

  // Debounce refresh requests to prevent excessive reloads
  const refreshTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const refreshConversations = useCallback((force = false) => {
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

  const loadConversation = useCallback((conversation: ConversationData) => {
    setCurrentConversationId(conversation.response_id);
    setEndpoint(conversation.endpoint);
    // Store the full conversation data for the chat page to use
    setConversationData(conversation);
    // Clear placeholder when loading a real conversation
    setPlaceholderConversation(null);
    setConversationLoaded(true);
    // Clear conversation docs to prevent duplicates when switching conversations
    setConversationDocs([]);
  }, []);

  const startNewConversation = useCallback(() => {
    // Clear current conversation data and reset state
    setCurrentConversationId(null);
    setPreviousResponseIds({ chat: null, langflow: null });
    setConversationData(null);
    setConversationDocs([]);
    setConversationLoaded(false);

    // Create a temporary placeholder conversation to show in sidebar
    const placeholderConversation: ConversationData = {
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

    setPlaceholderConversation(placeholderConversation);
    // Force immediate refresh to ensure sidebar shows correct state
    refreshConversations(true);
  }, [endpoint, refreshConversations]);

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
      setConversationLoaded,
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
