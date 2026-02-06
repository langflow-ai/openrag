"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

// Response types
interface SyncResponse {
  task_ids?: string[];
  status: string;
  message: string;
  connections_synced?: number;
  synced_connectors?: string[];
  skipped_connectors?: string[];
  errors?: Array<{ connector_type: string; error: string }> | null;
}

// Sync all cloud connectors
const syncAllConnectors = async (): Promise<SyncResponse> => {
  const response = await fetch("/api/connectors/sync-all", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || "Failed to sync connectors");
  }

  return response.json();
};

// Sync a specific connector type
const syncConnector = async (connectorType: string): Promise<SyncResponse> => {
  const response = await fetch(`/api/connectors/${connectorType}/sync`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({}),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || `Failed to sync ${connectorType}`);
  }

  return response.json();
};

export const useSyncAllConnectors = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: syncAllConnectors,
    onSettled: () => {
      // Invalidate and refetch search queries after a delay to allow sync to complete
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["search"] });
      }, 2000);
    },
  });
};

export const useSyncConnector = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: syncConnector,
    onSettled: () => {
      // Invalidate and refetch search queries after a delay to allow sync to complete
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["search"] });
      }, 2000);
    },
  });
};
