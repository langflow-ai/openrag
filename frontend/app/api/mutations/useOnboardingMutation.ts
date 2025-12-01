import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { ONBOARDING_OPENRAG_DOCS_FILTER_ID_KEY } from "@/lib/constants";

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
    onSuccess: (data) => {
      // Store OpenRAG Docs filter ID if returned
      if (data.openrag_docs_filter_id && typeof window !== "undefined") {
        localStorage.setItem(
          ONBOARDING_OPENRAG_DOCS_FILTER_ID_KEY,
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
