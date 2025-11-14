import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import type { Settings } from "../queries/useGetSettingsQuery";
import { useGetCurrentProviderModelsQuery } from "../queries/useGetModelsQuery";

export interface UpdateSettingsRequest {
  // Agent settings
  llm_model?: string;
  llm_provider?: string;
  system_prompt?: string;

  // Knowledge settings
  chunk_size?: number;
  chunk_overlap?: number;
  table_structure?: boolean;
  ocr?: boolean;
  picture_descriptions?: boolean;
  embedding_model?: string;
  embedding_provider?: string;

  // Provider-specific settings (for dialogs)
  model_provider?: string; // Deprecated, kept for backward compatibility
  api_key?: string;
  endpoint?: string;
  project_id?: string;

  // Provider-specific API keys
  openai_api_key?: string;
  anthropic_api_key?: string;
  watsonx_api_key?: string;
  watsonx_endpoint?: string;
  watsonx_project_id?: string;
  ollama_endpoint?: string;
}

export interface UpdateSettingsResponse {
  message: string;
  settings: Settings;
}

export const useUpdateSettingsMutation = (
  options?: Omit<
    UseMutationOptions<UpdateSettingsResponse, Error, UpdateSettingsRequest>,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();
  const { refetch: refetchModels } = useGetCurrentProviderModelsQuery();

  async function updateSettings(
    variables: UpdateSettingsRequest,
  ): Promise<UpdateSettingsResponse> {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(variables),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || "Failed to update settings");
    }

    return response.json();
  }

  return useMutation({
    mutationFn: updateSettings,
    onSuccess: (...args) => {
      queryClient.invalidateQueries({
        queryKey: ["settings"],
      });
      refetchModels(); // Refetch models for the settings page
      options?.onSuccess?.(...args);
    },
    onError: options?.onError,
    onSettled: options?.onSettled,
  });
};
