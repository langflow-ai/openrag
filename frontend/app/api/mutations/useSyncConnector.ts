"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { IngestSettings } from "@/components/cloud-picker/types";

// Response types
interface SyncResponse {
  task_ids?: string[];
  status: string;
  message: string;
  connections_synced?: number;
  synced_connectors?: string[];
  skipped_connectors?: string[];
  deleted_only_connectors?: string[];
  errors?: Array<{ connector_type: string; error: string }> | null;
}

export interface OrphanFile {
  document_id: string;
  filename: string;
}

export interface SyncPreviewResponse {
  connector_type: string;
  synced_count: number;
  orphans: OrphanFile[];
  /** False when strict gating aborted orphan detection (e.g. an active
   * connection was unauthenticated). UI should reflect that deletions
   * cannot be predicted in that case. */
  orphans_available: boolean;
}

export interface SyncAllPreviewResponse {
  orphans_by_type: Record<string, OrphanFile[]>;
  synced_count_by_type: Record<string, number>;
  orphans_available_by_type: Record<string, boolean>;
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
    settings?: IngestSettings;
    /** When true, ingest all files from the connector (bypasses the re-sync gate). */
    sync_all?: boolean;
    /** Restrict ingest to these bucket names (bucket connectors). */
    bucket_filter?: string[];
    /** When true, replace any indexed document with the same filename. */
    replace_duplicates?: boolean;
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

const syncConnectorPreview = async (
  connectorType: string,
): Promise<SyncPreviewResponse> => {
  const response = await fetch(
    `/api/connectors/${connectorType}/sync-preview`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    },
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.error || `Failed to preview sync for ${connectorType}`,
    );
  }

  return response.json();
};

const syncAllConnectorsPreview = async (): Promise<SyncAllPreviewResponse> => {
  const response = await fetch("/api/connectors/sync-all-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || "Failed to preview sync");
  }

  return response.json();
};

export const useSyncConnectorPreview = () =>
  useMutation({ mutationFn: syncConnectorPreview });

export const useSyncAllConnectorsPreview = () =>
  useMutation({ mutationFn: syncAllConnectorsPreview });
