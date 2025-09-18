import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

interface UpdateFlowSettingVariables {
  llm_model?: string;
  system_prompt?: string;
  embedding_model?: string;
  ocr?: boolean;
  picture_descriptions?: boolean;
  chunk_size?: number;
  chunk_overlap?: number;
}

interface UpdateFlowSettingResponse {
  message: string;
}

export const useUpdateFlowSettingMutation = (
  options?: Omit<
    UseMutationOptions<
      UpdateFlowSettingResponse,
      Error,
      UpdateFlowSettingVariables
    >,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

  async function updateFlowSetting(
    variables: UpdateFlowSettingVariables,
  ): Promise<UpdateFlowSettingResponse> {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(variables),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || "Failed to update settings");
    }

    return response.json();
  }

  return useMutation({
    mutationFn: updateFlowSetting,
    onSettled: () => {
      // Invalidate settings query to refetch updated data
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    ...options,
  });
};
