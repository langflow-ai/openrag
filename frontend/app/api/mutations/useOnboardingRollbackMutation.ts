import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

interface OnboardingRollbackResponse {
  message: string;
  cancelled_tasks: number;
  deleted_files: number;
}

interface RollbackParams {
  embedding_only?: boolean;
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

  async function rollbackOnboarding(
    params: RollbackParams | void,
  ): Promise<OnboardingRollbackResponse> {
    const requestBody = params || { embedding_only: false };

    const response = await fetch("/api/onboarding/rollback", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(requestBody),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || "Failed to rollback onboarding");
    }

    return response.json();
  }

  return useMutation({
    mutationFn: rollbackOnboarding,
    onSettled: () => {
      // Invalidate settings query to refetch updated data
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    ...options,
  });
};
