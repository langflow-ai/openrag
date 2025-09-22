import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

export interface OnboardingVariables {
  model_provider: string;
  api_key?: string;
  endpoint?: string;
  project_id?: string;
  embedding_model: string;
  llm_model: string;
  sample_data?: boolean;
}

interface OnboardingResponse {
  message: string;
  edited: boolean;
}

export const useOnboardingMutation = (
  options?: Omit<
    UseMutationOptions<
      OnboardingResponse,
      Error,
      OnboardingVariables
    >,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

  async function submitOnboarding(
    variables: OnboardingVariables,
  ): Promise<OnboardingResponse> {
    const response = await fetch("/api/onboarding", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(variables),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || "Failed to complete onboarding");
    }

    return response.json();
  }

  return useMutation({
    mutationFn: submitOnboarding,
    onSettled: () => {
      // Invalidate settings query to refetch updated data
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    ...options,
  });
};