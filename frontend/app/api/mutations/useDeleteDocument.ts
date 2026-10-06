"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

interface DeleteDocumentRequest {
  filename: string;
}

interface DeleteDocumentResponse {
  success: boolean;
  deleted_chunks: number;
  filename: string;
  message: string;
}

async function deleteDocumentByFilename(
  filename: string,
): Promise<DeleteDocumentResponse> {
  const response = await apiClient.post<DeleteDocumentResponse>(
    "/documents/delete-by-filename",
    { filename } satisfies DeleteDocumentRequest,
  );

  if (response.status < 200 || response.status >= 300) {
    const error = response.data as unknown as { error?: string };
    throw new Error(error.error || "Failed to delete document");
  }

  return response.data;
}

export const useDeleteDocument = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ filename }: DeleteDocumentRequest) =>
      deleteDocumentByFilename(filename),
    onSettled: () => {
      // Invalidate and refetch search queries to update the UI
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["search"] });
        queryClient.invalidateQueries({ queryKey: ["listFiles"] });
        // Connector "Browse Files" dialogs cache per-file ingestion state; drop
        // it so a deleted file no longer shows as "Ingested"/disabled there.
        queryClient.invalidateQueries({ queryKey: ["browseConnectionFiles"] });
      }, 1000);
    },
  });
};
