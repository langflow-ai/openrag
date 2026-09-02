"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

interface RefreshBomaRAGDocsResponse {
  message: string;
  refreshed: boolean;
}

const refreshBomaragDocs = async (): Promise<RefreshBomaRAGDocsResponse> => {
  const response = await fetch("/api/bomarag-docs/refresh", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    let errorMessage = "Failed to refresh BomaRAG docs";

    try {
      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        const error = await response.json();
        errorMessage = error.detail || error.error || errorMessage;
      } else {
        const text = (await response.text()).trim();
        if (text) {
          errorMessage = text;
        }
      }
    } catch {
      // Keep default fallback message for malformed/non-JSON bodies.
    }

    throw new Error(errorMessage);
  }

  return response.json();
};

export const useRefreshBomaragDocs = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: refreshBomaragDocs,
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"], exact: false });
      queryClient.invalidateQueries({ queryKey: ["search"], exact: false });
      queryClient.invalidateQueries({ queryKey: ["settings"], exact: false });
    },
  });
};
