"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { FAILED_INGESTIONS_QUERY_KEY } from "../queries/useFailedIngestionsQuery";

interface ClearFailedIngestionsRequest {
  /** Omit both to clear every failed document. */
  connectorType?: string;
  fileId?: string;
}

async function clearFailedIngestions({
  connectorType,
  fileId,
}: ClearFailedIngestionsRequest): Promise<{ cleared: number }> {
  const response = await apiClient.post<{ cleared: number }>(
    "/connectors/failed-ingestions/clear",
    { connector_type: connectorType, file_id: fileId },
  );
  if (response.status < 200 || response.status >= 300) {
    const err = (response.data ?? {}) as unknown as { error?: string };
    throw new Error(err.error || "Failed to clear failed documents");
  }
  return response.data;
}

/** "Retry" / "Clear failure state": forget failures so the next sync tries them again. */
export const useClearFailedIngestions = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: clearFailedIngestions,
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: FAILED_INGESTIONS_QUERY_KEY });
    },
  });
};
