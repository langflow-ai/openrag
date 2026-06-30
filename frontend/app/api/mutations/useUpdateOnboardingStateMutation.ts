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

import { useMutation, useQueryClient } from "@tanstack/react-query";

interface UpdateOnboardingStateVariables {
  current_step?: number;
  assistant_message?: {
    role: string;
    content: string;
    timestamp: string;
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
      const response = await fetch("/api/onboarding/state", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(variables),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || "Failed to update onboarding state");
      }

      return response.json();
    },
    onSuccess: () => {
      // Invalidate settings query to refetch updated onboarding state
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });
};

// Made with Bob
