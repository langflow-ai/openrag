"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

interface ShareDocumentRequest {
  filename: string;
  user_ids: string[];
}

interface ShareDocumentResponse {
  success: boolean;
  allowed_users: string[];
}

async function shareDocument(
  data: ShareDocumentRequest,
): Promise<ShareDocumentResponse> {
  const response = await fetch("/api/documents/acl/share", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || "Failed to share document");
  }

  return response.json();
}

export const useShareDocumentMutation = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: shareDocument,
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["document-acl", variables.filename],
      });
    },
  });
};
