"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

interface DeleteDocumentRequest {
  filename: string;
}

interface DeleteDocumentResponse {
  success: boolean;
  deleted_chunks: number;
  filename: string;
  message: string;
}

const deleteDocument = async (
  data: DeleteDocumentRequest,
): Promise<DeleteDocumentResponse> => {
  const response = await fetch("/api/documents/delete-by-filename", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || "Failed to delete document");
  }

  return response.json();
};

export const useDeleteDocument = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteDocument,
    onSettled: () => {
      // Invalidate and refetch search queries to update the UI
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["search"] });
      }, 1000);
    },
  });
};
