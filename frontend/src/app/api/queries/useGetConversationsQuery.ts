import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { EndpointType } from "@/contexts/chat-context";

export interface RawConversation {
  response_id: string;
  title: string;
  endpoint: string;
  messages: Array<{
    role: string;
    content: string;
    timestamp?: string;
    response_id?: string;
  }>;
  created_at?: string;
  last_activity?: string;
  previous_response_id?: string;
  total_messages: number;
  [key: string]: unknown;
}

export interface ChatConversation {
  response_id: string;
  title: string;
  endpoint: EndpointType;
  messages: Array<{
    role: string;
    content: string;
    timestamp?: string;
    response_id?: string;
  }>;
  created_at?: string;
  last_activity?: string;
  previous_response_id?: string;
  total_messages: number;
  [key: string]: unknown;
}

export interface ConversationHistoryResponse {
  conversations: RawConversation[];
  [key: string]: unknown;
}

export const useGetConversationsQuery = (
  endpoint: EndpointType,
  refreshTrigger?: number,
  options?: Omit<UseQueryOptions, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  async function getConversations(): Promise<ChatConversation[]> {
    try {
      // Fetch from the selected endpoint only
      const apiEndpoint =
        endpoint === "chat" ? "/api/chat/history" : "/api/langflow/history";

      const response = await fetch(apiEndpoint);

      if (!response.ok) {
        console.error(`Failed to fetch conversations: ${response.status}`);
        return [];
      }

      const history: ConversationHistoryResponse = await response.json();
      const rawConversations = history.conversations || [];

      // Cast conversations to proper type and ensure endpoint is correct
      const conversations: ChatConversation[] = rawConversations.map(
        (conv: RawConversation) => ({
          ...conv,
          endpoint: conv.endpoint as EndpointType,
        }),
      );

      // Sort conversations by last activity (most recent first)
      conversations.sort((a: ChatConversation, b: ChatConversation) => {
        const aTime = new Date(a.last_activity || a.created_at || 0).getTime();
        const bTime = new Date(b.last_activity || b.created_at || 0).getTime();
        return bTime - aTime;
      });

      return conversations;
    } catch (error) {
      console.error(`Failed to fetch ${endpoint} conversations:`, error);
      return [];
    }
  }

  const queryResult = useQuery(
    {
      queryKey: ["conversations", endpoint, refreshTrigger],
      placeholderData: (prev) => prev,
      queryFn: getConversations,
      staleTime: 0, // Always consider data stale to ensure fresh data on trigger changes
      gcTime: 5 * 60 * 1000, // Keep in cache for 5 minutes
      ...options,
    },
    queryClient,
  );

  return queryResult;
};
