/**
 * OpenRAG SDK documents client.
 */

import type { OpenRAGClient } from "./client";
import type {
  DeleteDocumentOptions,
  DeleteDocumentResponse,
  FileRecord,
  GetAllFilesOptions,
  GetAllFilesResponse,
  IngestResponse,
  IngestTaskStatus,
  ListFilesOptions,
  ListFilesResponse,
  NotFoundError,
} from "./types";

export interface IngestOptions {
  /** Path to file (Node.js only). */
  filePath?: string;
  /** File object (browser or Node.js). */
  file?: File | Blob;
  /** Filename when providing file/blob. */
  filename?: string;
  /** If true, poll until ingestion completes. Default: true. */
  wait?: boolean;
  /** Seconds between status checks when waiting. Default: 1. */
  pollInterval?: number;
  /** Maximum seconds to wait for completion. Default: 300. */
  timeout?: number;
}

export class DocumentsClient {
  constructor(private client: OpenRAGClient) {}

  /**
   * Ingest a document into the knowledge base.
   *
   * @param options - Ingest options (filePath or file+filename).
   * @returns IngestTaskStatus with final status if wait=true, IngestResponse with task_id if wait=false.
   */
  async ingest(
    options: IngestOptions
  ): Promise<IngestResponse | IngestTaskStatus> {
    const formData = new FormData();
    const wait = options.wait ?? true;
    const pollInterval = options.pollInterval ?? 1;
    const timeout = options.timeout ?? 300;

    if (options.filePath) {
      // Node.js: read file from path
      if (typeof globalThis.process !== "undefined") {
        const fs = await import("fs");
        const path = await import("path");
        const fileBuffer = fs.readFileSync(options.filePath);
        const filename = path.basename(options.filePath);
        const blob = new Blob([fileBuffer]);
        formData.append("file", blob, filename);
      } else {
        throw new Error("filePath is only supported in Node.js");
      }
    } else if (options.file) {
      if (!options.filename) {
        throw new Error("filename is required when providing file");
      }
      formData.append("file", options.file, options.filename);
    } else {
      throw new Error("Either filePath or file must be provided");
    }

    const response = await this.client._request(
      "POST",
      "/api/v1/documents/ingest",
      {
        body: formData,
        isMultipart: true,
      }
    );

    const data = await response.json();
    const ingestResponse: IngestResponse = {
      task_id: data.task_id,
      status: data.status ?? null,
      filename: data.filename ?? null,
    };

    if (!wait) {
      return ingestResponse;
    }

    // Poll for completion
    return await this.waitForTask(ingestResponse.task_id, pollInterval, timeout);
  }

  /**
   * Get the status of an ingestion task.
   *
   * @param taskId - The task ID returned from ingest().
   * @returns IngestTaskStatus with current task status.
   */
  async getTaskStatus(taskId: string): Promise<IngestTaskStatus> {
    const response = await this.client._request(
      "GET",
      `/api/v1/tasks/${taskId}`
    );
    const data = await response.json();
    return {
      task_id: data.task_id,
      status: data.status,
      total_files: data.total_files ?? 0,
      processed_files: data.processed_files ?? 0,
      successful_files: data.successful_files ?? 0,
      failed_files: data.failed_files ?? 0,
      files: data.files ?? {},
    };
  }

  /**
   * Wait for an ingestion task to complete.
   *
   * @param taskId - The task ID to wait for.
   * @param pollInterval - Seconds between status checks.
   * @param timeout - Maximum seconds to wait.
   * @returns IngestTaskStatus with final status.
   */
  async waitForTask(
    taskId: string,
    pollInterval: number = 1,
    timeout: number = 300
  ): Promise<IngestTaskStatus> {
    const startTime = Date.now();
    const timeoutMs = timeout * 1000;

    while (Date.now() - startTime < timeoutMs) {
      const status = await this.getTaskStatus(taskId);
      if (status.status === "completed" || status.status === "failed") {
        return status;
      }
      await this.sleep(pollInterval * 1000);
    }

    throw new Error(
      `Ingestion task ${taskId} did not complete within ${timeout}s`
    );
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /**
   * List ingested files with cursor-based composite-aggregation pagination (v2).
   *
   * @param options - Filtering, sorting, and cursor pagination options.
   * @returns ListFilesResponse with files list, approximate total, and next after_key cursor.
   */
  async listFiles(options: ListFilesOptions = {}): Promise<ListFilesResponse> {
    const params = new URLSearchParams();
    if (options.page !== undefined) params.set("page", String(options.page));
    if (options.page_size !== undefined) params.set("page_size", String(options.page_size));
    if (options.sort_by !== undefined) params.set("sort_by", options.sort_by);
    if (options.sort_order !== undefined) params.set("sort_order", options.sort_order);
    if (options.connector_type !== undefined) params.set("connector_type", options.connector_type);
    if (options.mimetype !== undefined) params.set("mimetype", options.mimetype);
    if (options.owner !== undefined) params.set("owner", options.owner);
    if (options.search !== undefined) params.set("search", options.search);
    if (options.after_key !== undefined) params.set("after_key", options.after_key);

    const qs = params.toString();
    const path = qs ? `/api/v2/files?${qs}` : "/api/v2/files";
    const response = await this.client._request("GET", path);
    const data = await response.json();

    return {
      files: (data.files ?? []) as FileRecord[],
      total: data.total ?? 0,
      is_approximate: data.is_approximate ?? true,
      page: data.page ?? 1,
      page_size: data.page_size ?? 25,
      after_key: data.after_key ?? null,
    };
  }

  /**
   * Return up to `limit` ingested files using simple offset pagination (v1).
   *
   * No cursor required or returned. Use this for a straightforward "get all files"
   * call without managing pagination state.
   *
   * @param options - Filtering, sorting, and limit options.
   * @returns GetAllFilesResponse with files list and total count.
   */
  async getAllFiles(options: GetAllFilesOptions = {}): Promise<GetAllFilesResponse> {
    const params = new URLSearchParams();
    if (options.limit !== undefined) params.set("limit", String(options.limit));
    if (options.sort_by !== undefined) params.set("sort_by", options.sort_by);
    if (options.sort_order !== undefined) params.set("sort_order", options.sort_order);
    if (options.connector_type !== undefined) params.set("connector_type", options.connector_type);
    if (options.mimetype !== undefined) params.set("mimetype", options.mimetype);
    if (options.owner !== undefined) params.set("owner", options.owner);
    if (options.search !== undefined) params.set("search", options.search);

    const qs = params.toString();
    const path = qs ? `/api/v1/files/getAll?${qs}` : "/api/v1/files/getAll";
    const response = await this.client._request("GET", path);
    const data = await response.json();

    return {
      files: (data.files ?? []) as FileRecord[],
      total: data.total ?? 0,
      page: data.page ?? 1,
      page_size: data.page_size ?? 100,
    };
  }

  /**
   * Delete document(s) from the knowledge base.
   *
   * Provide exactly one of:
   *   - filename: a single filename, or
   *   - { filename } / { filterId }: an options object.
   *
   * @returns DeleteDocumentResponse with deleted chunk count.
   */
  async delete(
    arg: string | DeleteDocumentOptions
  ): Promise<DeleteDocumentResponse> {
    const opts: DeleteDocumentOptions =
      typeof arg === "string" ? { filename: arg } : arg;

    if (!opts.filename === !opts.filterId) {
      throw new Error(
        "Provide exactly one of `filename` or `filterId`"
      );
    }

    const body: Record<string, string> = {};
    if (opts.filename) body["filename"] = opts.filename;
    if (opts.filterId) body["filter_id"] = opts.filterId;

    try {
      const response = await this.client._request("DELETE", "/api/v1/documents", {
        body: JSON.stringify(body),
      });

      const data = await response.json();
      return {
        success: data.success ?? false,
        deleted_chunks: data.deleted_chunks ?? 0,
        filename: data.filename ?? opts.filename ?? null,
        message: data.message ?? null,
        error: data.error ?? null,
        filenames: data.filenames ?? null,
        filter_id: data.filter_id ?? null,
        per_file: data.per_file ?? null,
      };
    } catch (error) {
      // Filename delete stays idempotent (404 -> success:false). Filter-id 404s
      // are caller errors (bad filter id) and should propagate.
      if (
        opts.filename &&
        (error as NotFoundError)?.statusCode === 404
      ) {
        return {
          success: false,
          deleted_chunks: 0,
          filename: opts.filename,
          message: null,
          error: (error as Error)?.message ?? "Resource not found",
        };
      }
      throw error;
    }
  }
}
