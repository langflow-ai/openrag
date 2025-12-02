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

  async function getConversations(context: { signal?: AbortSignal }): Promise<ChatConversation[]> {
    try {
      // Fetch from the selected endpoint only
      const apiEndpoint =
        endpoint === "chat" ? "/api/chat/history" : "/api/langflow/history";

      const response = await fetch(apiEndpoint, {
        signal: context.signal,
      });

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
      // Ignore abort errors - these are expected when requests are cancelled
      if (error instanceof Error && error.name === 'AbortError') {
        return [];
      }
      console.error(`Failed to fetch ${endpoint} conversations:`, error);
      return [];
    }
  }

  const queryResult = useQuery(
    {
      queryKey: ["conversations", endpoint, refreshTrigger],
      placeholderData: (prev) => prev,
      queryFn: getConversations,
      staleTime: 5000, // Consider data fresh for 5 seconds to prevent excessive refetching
      gcTime: 5 * 60 * 1000, // Keep in cache for 5 minutes
      networkMode: 'always', // Ensure requests can be cancelled
      refetchOnMount: false, // Don't refetch on every mount
      refetchOnWindowFocus: false, // Don't refetch when window regains focus
      ...options,
    },
    queryClient,
  );

  return queryResult;
};
