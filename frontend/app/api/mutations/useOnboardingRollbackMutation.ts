import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

interface OnboardingRollbackResponse {
  message: string;
  cancelled_tasks: number;
  deleted_files: number;
}

interface RollbackParams {
  embedding_only?: boolean;
}

async function rollbackOnboarding(
  params: RollbackParams | void,
): Promise<OnboardingRollbackResponse> {
  const requestBody = params || { embedding_only: false };

  const response = await apiClient.post<OnboardingRollbackResponse>(
    "/onboarding/rollback",
    requestBody,
  );

  if (response.status < 200 || response.status >= 300) {
    const text = typeof response.data === "string" ? response.data : "";
    let message = "Failed to rollback onboarding";
    try {
      const error =
        response.data && typeof response.data === "object"
          ? response.data
          : JSON.parse(text);
      if (error.error) message = error.error;
    } catch {}
    throw new Error(message);
  }

  return response.data;
}

export const useOnboardingRollbackMutation = (
  options?: Omit<
    UseMutationOptions<
      OnboardingRollbackResponse,
      Error,
      RollbackParams | void
    >,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: rollbackOnboarding,
    onSettled: () => {
      // Invalidate settings query to refetch updated data
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    ...options,
  });
};
