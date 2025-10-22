"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

export interface UploadPathRequest {
  path: string;
}

export interface UploadPathResponse {
  task_id?: string;
  id?: string;
  error?: string;
  status?: number;
}

const uploadPath = async (
  data: UploadPathRequest
): Promise<UploadPathResponse> => {
  const response = await fetch("/api/upload_path", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ path: data.path }),
  });

  const result = await response.json();

  // Handle different response statuses
  if (response.status === 201) {
    const taskId = result.task_id || result.id;

    if (!taskId) {
      throw new Error("No task ID received from server");
    }

    return { ...result, status: response.status };
  } else if (response.ok) {
    // Success but not 201
    return { ...result, status: response.status };
  } else {
    // Error response
    if (response.status === 400) {
      throw new Error(result.error || "Bad request");
    }
    throw new Error(result.error || "Upload failed");
  }
};

export const useUploadPath = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: uploadPath,
    onSettled: () => {
      // Invalidate tasks query to refresh the UI
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
};
