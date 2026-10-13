import {
  type MutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import type { EndpointType } from "@/contexts/chat-context";
import { apiClient } from "@/lib/api-client";

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
      const response = await apiClient.delete(`/sessions/${sessionId}`);

      if (response.status < 200 || response.status >= 300) {
        const errorData = response.data ?? {};
        throw new Error(
          errorData.error || `Failed to delete session: ${response.status}`,
        );
      }

      return response.data;
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
