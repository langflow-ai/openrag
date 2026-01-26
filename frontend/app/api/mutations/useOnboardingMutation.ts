import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { useUpdateOnboardingStateMutation } from "./useUpdateOnboardingStateMutation";

export interface OnboardingVariables {
  // Provider selection
  llm_provider?: string;
  embedding_provider?: string;

  // Models
  embedding_model?: string;
  llm_model?: string;

  // Provider-specific credentials
  openai_api_key?: string;
  anthropic_api_key?: string;
  watsonx_api_key?: string;
  watsonx_endpoint?: string;
  watsonx_project_id?: string;
  ollama_endpoint?: string;

  // Sample data
  sample_data?: boolean;
}

interface OnboardingResponse {
  message: string;
  edited: boolean;
  openrag_docs_filter_id?: string;
}

export const useOnboardingMutation = (
  options?: Omit<
    UseMutationOptions<OnboardingResponse, Error, OnboardingVariables>,
    "mutationFn"
  >
) => {
  const queryClient = useQueryClient();

  const updateOnboardingMutation = useUpdateOnboardingStateMutation();

  async function submitOnboarding(
    variables: OnboardingVariables
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
    onSuccess: (data) => {
      // Save OpenRAG docs filter ID if sample data was ingested
      if (data.openrag_docs_filter_id) {
        // Save to backend
        updateOnboardingMutation.mutateAsync({
          openrag_docs_filter_id: data.openrag_docs_filter_id,
        });

        console.log(
          "Saved OpenRAG docs filter ID:",
          data.openrag_docs_filter_id
        );
      }
    },
    onSettled: () => {
      // Invalidate settings query to refetch updated data
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    ...options,
  });
};
