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

  const response = await fetch("/api/upload_context", {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || "Failed to process document");
  }

  const result = await response.json();

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
}

export async function duplicateCheck(
  file: File,
): Promise<DuplicateCheckResponse> {
  const response = await fetch(
    `/api/documents/check-filename?filename=${encodeURIComponent(file.name)}`,
  );

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(
      errorText || `Failed to check duplicates: ${response.statusText}`,
    );
  }

  return response.json();
}

export async function uploadFiles(
  files: File[],
  replace = false,
): Promise<{ taskId: string; fileCount: number }> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("file", file);
  }
  formData.append("replace_duplicates", replace.toString());

  const uploadResponse = await fetch("/api/router/upload_ingest", {
    method: "POST",
    body: formData,
  });

  let payload: unknown;
  try {
    payload = await uploadResponse.json();
  } catch {
    throw new Error("Upload failed: unable to parse server response");
  }

  const json = typeof payload === "object" && payload !== null ? payload : {};

  if (!uploadResponse.ok) {
    const errorMessage = (json as { error?: string }).error || "Upload failed";
    throw new Error(errorMessage);
  }

  const taskId = (json as { task_id?: string }).task_id;
  const fileCount =
    (json as { file_count?: number }).file_count ?? files.length;

  if (!taskId) {
    throw new Error("Upload successful but no task ID returned");
  }

  return { taskId, fileCount };
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
): Promise<UploadFileResult> {
  try {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("replace_duplicates", replace.toString());
    if (createFilter) {
      formData.append("create_filter", "true");
    }

    const uploadResponse = await fetch("/api/router/upload_ingest", {
      method: "POST",
      body: formData,
    });

    let payload: unknown;
    try {
      payload = await uploadResponse.json();
    } catch (_error) {
      throw new Error("Upload failed: unable to parse server response");
    }

    const uploadIngestJson =
      typeof payload === "object" && payload !== null ? payload : {};

    if (!uploadResponse.ok) {
      const errorMessage =
        (uploadIngestJson as { error?: string }).error ||
        "Upload and ingest failed";
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
