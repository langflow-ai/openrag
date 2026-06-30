/* ******************************************************************************
 * IBM Confidential
 *
 * OCO Source Materials
 *
 *  Copyright IBM Corp. 2026  All Rights Reserved.
 *
 * The source code for this program is not published or otherwise divested
 * of its trade secrets, irrespective of what has been deposited with
 * the U.S. Copyright Office.
 ****************************************************************************** */

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

async function deleteDocumentByFilename(
  filename: string,
): Promise<DeleteDocumentResponse> {
  const response = await fetch("/api/documents/delete-by-filename", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ filename } satisfies DeleteDocumentRequest),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || "Failed to delete document");
  }

  return response.json();
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
      }, 1000);
    },
  });
};
