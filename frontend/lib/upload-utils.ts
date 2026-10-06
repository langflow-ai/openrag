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

/**
 * Read an upload response, preferring the server's own error message.
 *
 * A rejection does not always carry JSON: a proxy that caps the request body
 * answers 413 with an HTML page, and parsing that first would report "unable
 * to parse server response" and hide the real cause.
 */
async function readUploadResponse(
  response: Response,
  fallbackMessage: string,
): Promise<Record<string, unknown>> {
  let payload: unknown;
  let parsed = true;
  try {
    payload = await response.json();
  } catch {
    parsed = false;
  }

  const json =
    parsed && typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>)
      : {};

  if (response.ok) {
    if (!parsed) {
      throw new Error("Upload failed: unable to parse server response");
    }
    return json;
  }

  const serverError = json.error;
  if (typeof serverError === "string" && serverError) {
    throw new Error(serverError);
  }

  if (response.status === 413) {
    throw new Error(
      "File too large: the server rejected the upload (413). Ask an " +
        "administrator to raise the request body limit, or split the file.",
    );
  }

  throw new Error(
    response.statusText
      ? `${fallbackMessage} (${response.status} ${response.statusText})`
      : `${fallbackMessage} (${response.status})`,
  );
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

/**
 * Group files into upload requests bounded by both count and total bytes.
 *
 * Batching on count alone lets many small files form one oversized request —
 * at the default batch size of 25, twenty-five 50KB files already exceed a 1MB
 * body limit. A file bigger than the budget gets its own request, where the
 * server can reject it with a message naming the file.
 */
export function batchFilesBySizeAndCount(
  files: File[],
  maxCount: number,
  maxBytes: number,
): File[][] {
  const batches: File[][] = [];
  let current: File[] = [];
  let currentBytes = 0;

  for (const file of files) {
    const wouldExceedCount = current.length >= maxCount;
    const wouldExceedBytes =
      current.length > 0 && currentBytes + file.size > maxBytes;

    if (wouldExceedCount || wouldExceedBytes) {
      batches.push(current);
      current = [];
      currentBytes = 0;
    }

    current.push(file);
    currentBytes += file.size;
  }

  if (current.length > 0) {
    batches.push(current);
  }

  return batches;
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

  const uploadResponse = await fetch("/api/router/upload_ingest", {
    method: "POST",
    body: formData,
  });

  const json = await readUploadResponse(uploadResponse, "Upload failed");

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

    const uploadResponse = await fetch("/api/router/upload_ingest", {
      method: "POST",
      body: formData,
    });

    const uploadIngestJson = await readUploadResponse(
      uploadResponse,
      "Upload and ingest failed",
    );

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
