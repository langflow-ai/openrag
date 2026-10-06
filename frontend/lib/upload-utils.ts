import { apiClient } from "@/lib/api-client";

function getUploadErrorMessage(data: unknown): string {
  if (typeof data === "string") return data;
  if (!data || typeof data !== "object") return "";

  const payload = data as Record<string, unknown>;
  for (const key of ["error", "detail", "message"]) {
    if (typeof payload[key] === "string" && payload[key]) {
      return payload[key];
    }
  }
  return "";
}
export type UploadContextResult =
  | { type: "task"; taskId: string }
  | { type: "direct"; filename: string; responseId: string };

export async function uploadFileForContext(
  file: File,
  endpoint: string,
  previousResponseId: string | null,
): Promise<UploadContextResult> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("endpoint", endpoint);
  if (previousResponseId) {
    formData.append("previous_response_id", previousResponseId);
  }

  const response = await apiClient.post("/upload_context", formData);

  if (response.status < 200 || response.status >= 300) {
    const errorText = getUploadErrorMessage(response.data);
    throw new Error(errorText || "Failed to process document");
  }

  const result = response.data;

  if (response.status === 201) {
    const taskId = result.task_id || result.id;
    if (!taskId) {
      throw new Error("No task ID received from server");
    }
    return { type: "task", taskId };
  }

  const filename: unknown = result.filename;
  const responseId: unknown = result.response_id;
  if (typeof filename !== "string" || !filename) {
    throw new Error("Upload succeeded but server returned no filename");
  }
  if (typeof responseId !== "string" || !responseId) {
    throw new Error("Upload succeeded but server returned no response_id");
  }
  return { type: "direct", filename, responseId };
}

export interface DuplicateCheckResponse {
  exists: boolean;
  [key: string]: unknown;
}

export interface UploadFileResult {
  fileId: string;
  filePath: string;
  run: unknown;
  deletion: unknown;
  unified: boolean;
  raw: unknown;
  createFilter?: boolean;
  filename?: string;
  taskId?: string;
  /** Whether the backend honored preview=true (flag + run-mode gated). */
  previewMode?: boolean;
}

export async function duplicateCheck(
  file: File,
): Promise<DuplicateCheckResponse> {
  const response = await apiClient.get(
    `/documents/check-filename?filename=${encodeURIComponent(file.name)}`,
  );

  if (response.status < 200 || response.status >= 300) {
    const errorText = getUploadErrorMessage(response.data);
    throw new Error(
      errorText || `Failed to check duplicates: ${response.statusText}`,
    );
  }

  return response.data;
}

export async function uploadFiles(
  files: File[],
  replace = false,
  preview = false,
): Promise<{ taskId: string; fileCount: number; previewMode: boolean }> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("file", file);
  }
  formData.append("replace_duplicates", replace.toString());
  if (preview) {
    formData.append("preview", "true");
  }

  const uploadResponse = await apiClient.post(
    "/router/upload_ingest",
    formData,
  );

  let payload: unknown;
  try {
    payload = uploadResponse.data;
  } catch {
    throw new Error("Upload failed: unable to parse server response");
  }

  if (typeof payload === "string") {
    throw new Error("Upload failed: unable to parse server response");
  }

  const json = typeof payload === "object" && payload !== null ? payload : {};

  if (uploadResponse.status < 200 || uploadResponse.status >= 300) {
    const errorMessage = getUploadErrorMessage(json) || "Upload failed";
    throw new Error(errorMessage);
  }

  const taskId = (json as { task_id?: string }).task_id;
  const fileCount =
    (json as { file_count?: number }).file_count ?? files.length;
  const previewMode = Boolean(
    (json as { preview_mode?: boolean }).preview_mode,
  );

  if (!taskId) {
    throw new Error("Upload successful but no task ID returned");
  }

  return { taskId, fileCount, previewMode };
}

export interface UploadFileCallbacks {
  onComplete?: () => void;
  onError?: (filename: string, error: string) => void;
}

export async function uploadFile(
  file: File,
  replace = false,
  createFilter = false,
  callbacks?: UploadFileCallbacks,
  preview = false,
): Promise<UploadFileResult> {
  try {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("replace_duplicates", replace.toString());
    if (createFilter) {
      formData.append("create_filter", "true");
    }
    if (preview) {
      formData.append("preview", "true");
    }

    const uploadResponse = await apiClient.post(
      "/router/upload_ingest",
      formData,
    );

    let payload: unknown;
    try {
      payload = uploadResponse.data;
    } catch (_error) {
      throw new Error("Upload failed: unable to parse server response");
    }

    if (typeof payload === "string") {
      throw new Error("Upload failed: unable to parse server response");
    }

    const uploadIngestJson =
      typeof payload === "object" && payload !== null ? payload : {};

    if (uploadResponse.status < 200 || uploadResponse.status >= 300) {
      const errorMessage =
        getUploadErrorMessage(uploadIngestJson) || "Upload and ingest failed";
      throw new Error(errorMessage);
    }

    const fileId =
      (uploadIngestJson as { upload?: { id?: string } }).upload?.id ||
      (uploadIngestJson as { id?: string }).id ||
      (uploadIngestJson as { task_id?: string }).task_id;
    const taskId = (uploadIngestJson as { task_id?: string }).task_id;
    const filePath =
      (uploadIngestJson as { upload?: { path?: string } }).upload?.path ||
      (uploadIngestJson as { path?: string }).path ||
      "uploaded";
    const runJson = (uploadIngestJson as { ingestion?: unknown }).ingestion;
    const deletionJson = (uploadIngestJson as { deletion?: unknown }).deletion;

    if (!fileId) {
      throw new Error("Upload successful but no file id returned");
    }

    if (
      runJson &&
      typeof runJson === "object" &&
      "status" in (runJson as Record<string, unknown>) &&
      (runJson as { status?: string }).status !== "COMPLETED" &&
      (runJson as { status?: string }).status !== "SUCCESS"
    ) {
      const errorMsg =
        (runJson as { error?: string }).error || "Ingestion pipeline failed";
      throw new Error(
        `Ingestion failed: ${errorMsg}. Try setting DISABLE_INGEST_WITH_LANGFLOW=true if you're experiencing Langflow component issues.`,
      );
    }

    const shouldCreateFilter = (uploadIngestJson as { create_filter?: boolean })
      .create_filter;
    const filename = (uploadIngestJson as { filename?: string }).filename;
    const previewMode = Boolean(
      (uploadIngestJson as { preview_mode?: boolean }).preview_mode,
    );

    const result: UploadFileResult = {
      fileId,
      filePath,
      run: runJson,
      deletion: deletionJson,
      unified: true,
      raw: uploadIngestJson,
      createFilter: shouldCreateFilter,
      filename,
      taskId,
      previewMode,
    };

    return result;
  } catch (error) {
    try {
      callbacks?.onError?.(
        file.name,
        error instanceof Error ? error.message : "Upload failed",
      );
    } catch (cbErr) {
      console.warn("uploadFile: onError callback threw", cbErr);
    }
    throw error;
  } finally {
    try {
      callbacks?.onComplete?.();
    } catch (cbErr) {
      console.warn("uploadFile: onComplete callback threw", cbErr);
    }
  }
}
