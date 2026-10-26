"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

interface RefreshOpenRAGDocsResponse {
  message: string;
  refreshed: boolean;
}

const refreshOpenragDocs = async (): Promise<RefreshOpenRAGDocsResponse> => {
  const response = await apiClient.post<unknown>("/openrag-docs/refresh");

  if (response.status < 200 || response.status >= 300) {
    let errorMessage = "Failed to refresh OpenRAG docs";

    try {
      if (typeof response.data === "object" && response.data !== null) {
        const error = response.data as { detail?: string; error?: string };
        errorMessage = error.detail || error.error || errorMessage;
      } else if (typeof response.data === "string" && response.data.trim()) {
        errorMessage = response.data.trim();
      }
    } catch {
      // Keep default fallback message for malformed/non-JSON bodies.
    }

    throw new Error(errorMessage);
  }

  return response.data as RefreshOpenRAGDocsResponse;
};

export const useRefreshOpenragDocs = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: refreshOpenragDocs,
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"], exact: false });
      queryClient.invalidateQueries({ queryKey: ["search"], exact: false });
      queryClient.invalidateQueries({ queryKey: ["settings"], exact: false });
    },
  });
};
