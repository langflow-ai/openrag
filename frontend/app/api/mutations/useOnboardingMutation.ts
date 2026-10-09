import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";
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
  openai_base_url?: string;
  anthropic_api_key?: string;
  watsonx_api_key?: string;
  watsonx_endpoint?: string;
  watsonx_project_id?: string;
  ollama_endpoint?: string;
  provider_credentials?: Record<string, Record<string, string>>;
  provider_credential_removals?: Record<string, string[]>;
  provider_auth_methods?: Record<string, string>;
}

interface OnboardingResponse {
  message: string;
  edited: boolean;
  openrag_docs_filter_id?: string;
  task_id?: string;
  chunk_size_adjusted_to?: number | null;
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
    ...options,
    mutationFn: submitOnboarding,
    onSuccess: async (data, variables, onMutateResult, context) => {
      // Save OpenRAG docs filter ID if sample data was ingested
      if (data.openrag_docs_filter_id) {
        await updateOnboardingMutation.mutateAsync({
          openrag_docs_filter_id: data.openrag_docs_filter_id,
        });
      }
      if (typeof data.chunk_size_adjusted_to === "number") {
        toast.info(`Chunk size reduced to ${data.chunk_size_adjusted_to}`, {
          description:
            "OpenRAG adjusted ingestion chunks to stay within watsonx.ai on-prem embedding limits.",
        });
      }
      await options?.onSuccess?.(data, variables, onMutateResult, context);
    },
    onSettled: async (data, error, variables, onMutateResult, context) => {
      // Invalidate settings query to refetch updated onboarding state
      await queryClient.invalidateQueries({ queryKey: ["settings"] });
      await options?.onSettled?.(
        data,
        error,
        variables,
        onMutateResult,
        context,
      );
    },
  });
};
