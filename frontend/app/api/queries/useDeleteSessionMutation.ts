import {
  type MutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import type { EndpointType } from "@/contexts/chat-context";

interface DeleteSessionParams {
  sessionId: string;
  endpoint: EndpointType;
}

interface DeleteSessionResponse {
  success: boolean;
  message: string;
}

export const useDeleteSessionMutation = (
  options?: Omit<
    MutationOptions<DeleteSessionResponse, Error, DeleteSessionParams>,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

  return useMutation<DeleteSessionResponse, Error, DeleteSessionParams>({
    mutationFn: async ({ sessionId }: DeleteSessionParams) => {
      const response = await fetch(`/api/sessions/${sessionId}`, {
        method: "DELETE",
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(
          errorData.error || `Failed to delete session: ${response.status}`,
        );
      }

      return response.json();
    },
    onSettled: (_data, _error, variables) => {
      // Invalidate conversations query to refresh the list
      // Use a slight delay to ensure the success callback completes first
      setTimeout(() => {
        queryClient.invalidateQueries({
          queryKey: ["conversations", variables.endpoint],
        });

        // Also invalidate any specific conversation queries
        queryClient.invalidateQueries({
          queryKey: ["conversations"],
        });
      }, 0);
    },
    ...options,
  });
};
