"use client";

import React, { useState } from "react";
import { UnifiedCloudPicker, CloudFile } from "@/components/cloud-picker";
import { useTask } from "@/contexts/task-context";

// CloudFile interface is now imported from the unified cloud picker

export default function ConnectorsPage() {
  const { addTask } = useTask();
  const [selectedFiles, setSelectedFiles] = useState<CloudFile[]>([]);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [syncResult, setSyncResult] = useState<{
    processed?: number;
    total?: number;
    status?: string;
    error?: string;
    added?: number;
    errors?: number;
  } | null>(null);

  const handleFileSelection = (files: CloudFile[]) => {
    setSelectedFiles(files);
  };

  const handleSync = async (connector: {
    connectionId: string;
    type: string;
  }) => {
    if (!connector.connectionId || selectedFiles.length === 0) return;

    setIsSyncing(true);
    setSyncResult(null);

    try {
      const syncBody: {
        connection_id: string;
        max_files?: number;
        selected_files?: string[];
      } = {
        connection_id: connector.connectionId,
        selected_files: selectedFiles.map((file) => file.id),
      };

      const response = await fetch(`/api/connectors/${connector.type}/sync`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(syncBody),
      });

      const result = await response.json();

      if (response.status === 201) {
        const taskId = result.task_id;
        if (taskId) {
          addTask(taskId);
          setSyncResult({
            processed: 0,
            total: selectedFiles.length,
            status: "started",
          });
        }
      } else if (response.ok) {
        setSyncResult(result);
      } else {
        console.error("Sync failed:", result.error);
        setSyncResult({ error: result.error || "Sync failed" });
      }
    } catch (error) {
      console.error("Sync error:", error);
      setSyncResult({ error: "Network error occurred" });
    } finally {
      setIsSyncing(false);
    }
  };

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-4">Connectors</h1>

      <div className="mb-6">
        <p className="text-sm text-gray-600 mb-4">
          This is a demo page for the Google Drive picker component. For full
          connector functionality, visit the Settings page.
        </p>

        <UnifiedCloudPicker
          provider="google_drive"
          onFileSelected={handleFileSelection}
          selectedFiles={selectedFiles}
          isAuthenticated={false} // This would come from auth context in real usage
          accessToken={undefined} // This would come from connected account
          isIngesting={isSyncing}
        />
      </div>

      {selectedFiles.length > 0 && (
        <div className="space-y-4">
          <button
            onClick={() =>
              handleSync({
                connectionId: "google-drive-connection-id",
                type: "google-drive",
              })
            }
            disabled={isSyncing}
            className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSyncing ? (
              <>Syncing {selectedFiles.length} Selected Items...</>
            ) : (
              <>Sync {selectedFiles.length} Selected Items</>
            )}
          </button>

          {syncResult && (
            <div className="p-3 bg-gray-100 rounded text-sm">
              {syncResult.error ? (
                <div className="text-red-600">Error: {syncResult.error}</div>
              ) : syncResult.status === "started" ? (
                <div className="text-blue-600">
                  Sync started for {syncResult.total} files. Check the task
                  notification for progress.
                </div>
              ) : (
                <div className="text-green-600">
                  <div>Processed: {syncResult.processed || 0}</div>
                  <div>Added: {syncResult.added || 0}</div>
                  {syncResult.errors && <div>Errors: {syncResult.errors}</div>}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
