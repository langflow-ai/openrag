import { apiClient } from "@/lib/api-client";
import { formatFileSize } from "@/lib/file-format";

const DEFAULT_MAX_UPLOAD_MB = 100;
const DEFAULT_MAX_UPLOAD_BYTES = DEFAULT_MAX_UPLOAD_MB * 1024 * 1024;

let maxUploadBytesRequest: Promise<number> | null = null;

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

/** Turn an nginx HTML 413 into a short line a toast can show. */
function plainTextBody(body: string): string {
  const text = body.includes("<")
    ? body
        .replace(/<[^>]*>/g, " ")
        .replace(/\s+/g, " ")
        .trim()
    : body.trim();
  if (!text) return "Upload failed";
  return text.length > 300 ? `${text.slice(0, 300)}…` : text;
}

function uploadErrorText(data: unknown, fallback: string): string {
  if (typeof data === "string") {
    if (!data.trim()) return fallback;
    return plainTextBody(data);
  }
  return getUploadErrorMessage(data) || fallback;
}

export function resetUploadLimitCache(): void {
  maxUploadBytesRequest = null;
}

export async function getMaxUploadBytes(): Promise<number> {
  if (!maxUploadBytesRequest) {
    maxUploadBytesRequest = apiClient
      .get("/upload_options")
      .then((response) => {
        const mb = response.data?.max_upload_mb;
        if (
          response.status >= 200 &&
          response.status < 300 &&
          typeof mb === "number" &&
          mb > 0
        ) {
          return mb * 1024 * 1024;
        }
        return DEFAULT_MAX_UPLOAD_BYTES;
      })
      .catch(() => DEFAULT_MAX_UPLOAD_BYTES);
  }
  return maxUploadBytesRequest;
}

export function uploadTooLargeMessage(
  filename: string,
  sizeBytes: number,
  limitBytes: number,
): string {
  const limitMb = limitBytes / (1024 * 1024);
  const limitLabel = Number.isInteger(limitMb)
    ? String(limitMb)
    : limitMb.toFixed(1);
  return `"${filename}" is ${formatFileSize(sizeBytes)}. The upload limit is ${limitLabel} MB (OPENRAG_MAX_UPLOAD_MB).`;
}

/** Text shown in chat when a context upload fails. */
export function uploadFailureText(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return "Failed to process document. Please try again.";
}

/** Duplicates that were actually sent; an oversized duplicate was skipped. */
export function countSentDuplicates(
  sentNames: string[],
  duplicateNames: string[],
): number {
  const sent = new Set(sentNames);
  return duplicateNames.filter((name) => sent.has(name)).length;
}

/**
 * Success line for a folder upload. Null when nothing was sent, so callers
 * do not report a failure or a success for files that were only skipped.
 */
export function folderUploadSuccessText(
  sentCount: number,
  oversizedCount: number,
  lead: string,
  extraParts: string[] = [],
): string | null {
  if (sentCount <= 0) return null;
  const parts = extraParts.filter((part) => part.length > 0);
  if (oversizedCount > 0) {
    parts.push(`skipped ${oversizedCount} over the upload limit`);
  }
  const suffix = parts.length > 0 ? `, ${parts.join(", ")}` : "";
  return `${lead}${suffix}`;
}

export async function assertFilesWithinUploadLimit(
  files: File[],
): Promise<void> {
  const limitBytes = await getMaxUploadBytes();
  for (const file of files) {
    if (file.size > limitBytes) {
      throw new Error(uploadTooLargeMessage(file.name, file.size, limitBytes));
    }
  }
}

/**
 * Split a folder into requests that stay within the file-count limit and the
 * upload byte budget. A file larger than the budget is returned separately so
 * it is never posted.
 */
export function packUploadBatches(
  files: File[],
  maxCount: number,
  maxBytes: number,
): { batches: File[][]; oversized: File[] } {
  const countLimit = Math.max(1, maxCount);
  const oversized: File[] = [];
  const batches: File[][] = [];
  let current: File[] = [];
  let currentBytes = 0;

  for (const file of files) {
    if (file.size > maxBytes) {
      oversized.push(file);
      continue;
    }
    const nextWouldExceedCount = current.length >= countLimit;
    const nextWouldExceedBytes = currentBytes + file.size > maxBytes;
    if (current.length > 0 && (nextWouldExceedCount || nextWouldExceedBytes)) {
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
  return { batches, oversized };
}
export type UploadContextResult =
  | { type: "task"; taskId: string }
  | { type: "direct"; filename: string; responseId: string };

export async function uploadFileForContext(
  file: File,
  endpoint: string,
  previousResponseId: string | null,
): Promise<UploadContextResult> {
  await assertFilesWithinUploadLimit([file]);

  const formData = new FormData();
  formData.append("file", file);
  formData.append("endpoint", endpoint);
  if (previousResponseId) {
    formData.append("previous_response_id", previousResponseId);
  }

  const response = await apiClient.post("/upload_context", formData);

  if (response.status < 200 || response.status >= 300) {
    throw new Error(
      uploadErrorText(response.data, "Failed to process document"),
    );
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
  await assertFilesWithinUploadLimit(files);

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
    if (uploadResponse.status < 200 || uploadResponse.status >= 300) {
      throw new Error(plainTextBody(payload));
    }
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
    await assertFilesWithinUploadLimit([file]);

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
      if (uploadResponse.status < 200 || uploadResponse.status >= 300) {
        throw new Error(plainTextBody(payload));
      }
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
