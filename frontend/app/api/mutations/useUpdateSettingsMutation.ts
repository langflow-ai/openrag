import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { useGetCurrentProviderModelsQuery } from "../queries/useGetModelsQuery";
import type { Settings } from "../queries/useGetSettingsQuery";

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
  remove_ollama_config?: boolean;
  remove_openai_config?: boolean;
  remove_anthropic_config?: boolean;
  remove_watsonx_config?: boolean;
  // Bypass the "this provider's embedding models are still in use" guard.
  force_remove?: boolean;
}

export interface AffectedEmbeddingModel {
  model: string;
  doc_count: number;
}

// Typed error that preserves the structured 409 payload returned by
// POST /api/settings when removing a provider whose embedding models are
// still referenced by indexed documents.
export class UpdateSettingsError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly affectedProvider?: string;
  readonly affectedModels?: AffectedEmbeddingModel[];

  constructor(status: number, data: Record<string, unknown>) {
    const message =
      typeof data.error === "string" ? data.error : "Failed to update settings";
    super(message);
    this.name = "UpdateSettingsError";
    this.status = status;
    this.code = typeof data.code === "string" ? data.code : undefined;
    this.affectedProvider =
      typeof data.affected_provider === "string"
        ? data.affected_provider
        : undefined;
    this.affectedModels = Array.isArray(data.affected_models)
      ? (data.affected_models as AffectedEmbeddingModel[])
      : undefined;
  }
}

export const isEmbeddingProviderInUseError = (
  err: unknown,
): err is UpdateSettingsError =>
  err instanceof UpdateSettingsError &&
  err.code === "embedding_provider_in_use" &&
  Array.isArray(err.affectedModels) &&
  err.affectedModels.length > 0;

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
      throw new UpdateSettingsError(response.status, errorData);
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
