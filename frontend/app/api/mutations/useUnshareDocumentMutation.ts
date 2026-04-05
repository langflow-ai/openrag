"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

interface UnshareDocumentRequest {
  filename: string;
  user_ids: string[];
}

interface UnshareDocumentResponse {
  success: boolean;
  allowed_users: string[];
}

async function unshareDocument(
  data: UnshareDocumentRequest,
): Promise<UnshareDocumentResponse> {
  const response = await fetch("/api/documents/acl/unshare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || "Failed to unshare document");
  }

  return response.json();
}

export const useUnshareDocumentMutation = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: unshareDocument,
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["document-acl", variables.filename],
      });
    },
  });
};
