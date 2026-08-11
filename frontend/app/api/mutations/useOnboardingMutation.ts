import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { formatProviderErrorMessage } from "@/lib/chat-stream-errors";
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
  azure_ai_foundry_api_key?: string;
  azure_ai_foundry_endpoint?: string;
  azure_ai_foundry_api_version?: string;
  azure_openai_api_key?: string;
  azure_openai_endpoint?: string;
  azure_openai_api_version?: string;
}

interface OnboardingResponse {
  message: string;
  edited: boolean;
  openrag_docs_filter_id?: string;
  task_id?: string;
}

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
    const error = await response.json().catch(() => ({}));
    const raw =
      error && typeof error === "object" && typeof error.error === "string"
        ? error.error
        : "Failed to complete onboarding";
    throw new Error(formatProviderErrorMessage(raw));
  }

  return response.json();
}

export const useOnboardingMutation = (
  options?: Omit<
    UseMutationOptions<OnboardingResponse, Error, OnboardingVariables>,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

  const updateOnboardingMutation = useUpdateOnboardingStateMutation();

  return useMutation({
    mutationFn: submitOnboarding,
    onSuccess: (data) => {
      // Save OpenRAG docs filter ID if sample data was ingested
      if (data.openrag_docs_filter_id) {
        // Save to backend
        updateOnboardingMutation.mutateAsync({
          openrag_docs_filter_id: data.openrag_docs_filter_id,
        });
      }
    },
    onSettled: () => {
      // Invalidate settings query to refetch updated data
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    ...options,
  });
};
