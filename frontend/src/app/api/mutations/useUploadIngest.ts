"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

export interface UploadIngestRequest {
  file: File;
  replaceDuplicates: boolean;
}

export interface UploadIngestResponse {
  upload?: {
    id?: string;
    path?: string;
  };
  id?: string;
  task_id?: string;
  path?: string;
  ingestion?: {
    status: string;
    error?: string;
  };
  deletion?: {
    status: string;
    file_id?: string;
    error?: string;
  };
  error?: string;
}

const uploadIngest = async (
  data: UploadIngestRequest
): Promise<UploadIngestResponse> => {
  const formData = new FormData();
  formData.append("file", data.file);
  formData.append("replace_duplicates", data.replaceDuplicates.toString());

  const response = await fetch("/api/router/upload_ingest", {
    method: "POST",
    body: formData,
  });

  const json = await response.json();

  if (!response.ok) {
    throw new Error(json?.error || "Upload and ingest failed");
  }

  // Extract results from the response
  const fileId = json?.upload?.id || json?.id || json?.task_id;

  if (!fileId) {
    throw new Error("Upload successful but no file id returned");
  }

  // Check if ingestion actually succeeded
  const runJson = json?.ingestion;
  if (
    runJson &&
    runJson.status !== "COMPLETED" &&
    runJson.status !== "SUCCESS"
  ) {
    const errorMsg = runJson.error || "Ingestion pipeline failed";
    throw new Error(
      `Ingestion failed: ${errorMsg}. Try setting DISABLE_INGEST_WITH_LANGFLOW=true if you're experiencing Langflow component issues.`
    );
  }

  return json;
};

export const useUploadIngest = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: uploadIngest,
    onSettled: (data) => {
      // Log deletion status if provided
      const deleteResult = data?.deletion;
      if (deleteResult) {
        if (deleteResult.status === "deleted") {
          console.log(
            "File successfully cleaned up from Langflow:",
            deleteResult.file_id
          );
        } else if (deleteResult.status === "delete_failed") {
          console.warn(
            "Failed to cleanup file from Langflow:",
            deleteResult.error
          );
        }
      }

      // Invalidate tasks query to refresh the UI
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
};
