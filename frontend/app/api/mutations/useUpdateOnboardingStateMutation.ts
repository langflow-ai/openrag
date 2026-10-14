import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { FunctionCall } from "@/app/chat/_types/types";
import { apiClient } from "@/lib/api-client";

interface UpdateOnboardingStateVariables {
  current_step?: number;
  assistant_message?: {
    role: string;
    content: string;
    timestamp: string;
    functionCalls?: FunctionCall[] | null;
  } | null;
  selected_nudge?: string | null;
  card_steps?: Record<string, unknown> | null;
  upload_steps?: Record<string, unknown> | null;
  openrag_docs_filter_id?: string | null;
  user_doc_filter_id?: string | null;
}

export const useUpdateOnboardingStateMutation = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (variables: UpdateOnboardingStateVariables) => {
      const response = await apiClient.post("/onboarding/state", variables);

      if (response.status < 200 || response.status >= 300) {
        const error = response.data ?? {};
        throw new Error(error.error || "Failed to update onboarding state");
      }

      return response.data;
    },
    onSuccess: () => {
      // Invalidate settings query to refetch updated onboarding state
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });
};

// Made with Bob
