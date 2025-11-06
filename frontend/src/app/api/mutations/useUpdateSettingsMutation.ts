import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import type { Settings } from "../queries/useGetSettingsQuery";

export interface UpdateSettingsRequest {
  // Agent settings
  llm_model?: string;
  system_prompt?: string;

  // Knowledge settings
  chunk_size?: number;
  chunk_overlap?: number;
  table_structure?: boolean;
  ocr?: boolean;
  picture_descriptions?: boolean;
  embedding_model?: string;

  // Provider settings
  model_provider?: string;
  api_key?: string;
  endpoint?: string;
  project_id?: string;
}

export interface UpdateSettingsResponse {
  message: string;
  settings: Settings;
}

export const useUpdateSettingsMutation = (
  options?: Omit<
    UseMutationOptions<UpdateSettingsResponse, Error, UpdateSettingsRequest>,
    "mutationFn"
  >
) => {
  const queryClient = useQueryClient();

  async function updateSettings(
    variables: UpdateSettingsRequest
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
      options?.onSuccess?.(...args);
    },
    onError: options?.onError,
    onSettled: options?.onSettled,
  });
};
