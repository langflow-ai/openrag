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

interface RefreshOpenRAGDocsResponse {
  message: string;
  refreshed: boolean;
}

const refreshOpenragDocs = async (): Promise<RefreshOpenRAGDocsResponse> => {
  const response = await fetch("/api/openrag-docs/refresh", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    let errorMessage = "Failed to refresh OpenRAG docs";

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
