"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

export interface UploadBucketRequest {
  s3Url: string;
}

export interface UploadBucketResponse {
  task_id?: string;
  id?: string;
  error?: string;
  status?: number;
}

const uploadBucket = async (
  data: UploadBucketRequest
): Promise<UploadBucketResponse> => {
  const response = await fetch("/api/upload_bucket", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ s3_url: data.s3Url }),
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
    throw new Error(result.error || "S3 upload failed");
  }
};

export const useUploadBucket = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: uploadBucket,
    onSettled: () => {
      // Invalidate tasks query to refresh the UI
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
};
