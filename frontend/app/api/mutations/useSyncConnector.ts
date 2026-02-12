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
const syncConnector = async ({
  connectorType,
  body,
}: {
  connectorType: string;
  body?: {
    connection_id?: string;
    max_files?: number;
    selected_files?: Array<{
      id: string;
      name: string;
      mimeType: string;
      downloadUrl?: string;
      size?: number;
    }>;
    settings?: any;
  };
}): Promise<SyncResponse> => {
  const response = await fetch(`/api/connectors/${connectorType}/sync`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body || {}),
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
      // Immediately refetch tasks so new sync jobs appear in the task list
      queryClient.invalidateQueries({ queryKey: ["tasks"], exact: false });
    },
  });
};

export const useSyncConnector = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: syncConnector,
    onSettled: () => {
      // Immediately refetch tasks so new sync jobs appear in the task list
      queryClient.invalidateQueries({ queryKey: ["tasks"], exact: false });
    },
  });
};
