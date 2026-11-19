import {
  type UseMutationOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useAuth } from "@/contexts/auth-context";
import { apiClient } from "@/lib/api-client";

export type FeedbackRating = "up" | "down";

export interface MessageFeedbackRequest {
  conversationId: string;
  messageId: string;
  rating: FeedbackRating;
  /** Every submission replaces the whole value; null clears the comment. */
  comment: string | null;
}

export interface SavedMessageFeedback {
  message_id: string;
  rating: FeedbackRating;
  comment: string | null;
  created_at: string;
  updated_at: string;
}

/** Cache scoped to identity, conversation and message. */
export const messageFeedbackKey = (
  identity: string | undefined,
  conversationId: string | undefined,
  messageId: string | undefined,
) => ["message-feedback", identity ?? "anon", conversationId, messageId];

async function submitFeedback(
  variables: MessageFeedbackRequest,
): Promise<SavedMessageFeedback> {
  const response = await apiClient.post<SavedMessageFeedback>(
    `/chat/${encodeURIComponent(variables.conversationId)}/messages/${encodeURIComponent(variables.messageId)}/feedback`,
    { rating: variables.rating, comment: variables.comment },
  );
  if (response.status < 200 || response.status >= 300) {
    throw new Error("Failed to save feedback");
  }
  return response.data;
}

export const useMessageFeedbackMutation = (
  options?: Omit<
    UseMutationOptions<SavedMessageFeedback, Error, MessageFeedbackRequest>,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const identity = user?.user_id;

  return useMutation({
    mutationFn: submitFeedback,
    onSuccess: (saved, variables, ...rest) => {
      queryClient.setQueryData(
        messageFeedbackKey(
          identity,
          variables.conversationId,
          variables.messageId,
        ),
        saved,
      );
      // Keep the conversation-history snapshot in step, so a remount after the
      // message-feedback cache entry is collected still shows the saved vote.
      queryClient.setQueriesData<
        Array<{
          response_id: string;
          messages: Array<{ message_id?: string; feedback?: unknown }>;
        }>
      >({ queryKey: ["conversations"] }, (old) =>
        Array.isArray(old)
          ? old.map((conversation) =>
              conversation.response_id === variables.conversationId
                ? {
                    ...conversation,
                    messages: conversation.messages.map((message) =>
                      message.message_id === variables.messageId
                        ? {
                            ...message,
                            feedback: {
                              rating: saved.rating,
                              comment: saved.comment,
                              created_at: saved.created_at,
                              updated_at: saved.updated_at,
                            },
                          }
                        : message,
                    ),
                  }
                : conversation,
            )
          : old,
      );
      options?.onSuccess?.(saved, variables, ...rest);
    },
    onError: options?.onError,
    onSettled: options?.onSettled,
  });
};

/**
 * Canonical feedback for one answer: the latest of the server value restored
 * from history and the value saved this session. Local selection is never
 * authoritative; it only exists once the server has confirmed it.
 */
export function useCanonicalMessageFeedback(
  conversationId: string | undefined,
  messageId: string | undefined,
  fromHistory:
    | { rating: FeedbackRating; comment: string | null; updated_at?: string }
    | null
    | undefined,
) {
  const { user } = useAuth();
  const { data: saved } = useQuery<SavedMessageFeedback | null>({
    queryKey: messageFeedbackKey(user?.user_id, conversationId, messageId),
    queryFn: () => null,
    enabled: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
  if (
    saved &&
    fromHistory?.updated_at &&
    fromHistory.updated_at > saved.updated_at
  ) {
    return fromHistory;
  }
  return saved ?? fromHistory ?? null;
}
