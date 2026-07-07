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
    const text = await response.text();
    let message = "Failed to rollback onboarding";
    try {
      const error = JSON.parse(text);
      if (error.error) message = error.error;
    } catch {}
    throw new Error(message);
  }

  return response.json();
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
