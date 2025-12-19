/**
 * OpenRAG SDK documents client.
 */

import type { OpenRAGClient } from "./client";
import type {
  DeleteDocumentResponse,
  IngestResponse,
  IngestTaskStatus,
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
   * Delete a document from the knowledge base.
   *
   * @param filename - Name of the file to delete.
   * @returns DeleteDocumentResponse with deleted chunk count.
   */
  async delete(filename: string): Promise<DeleteDocumentResponse> {
    const response = await this.client._request("DELETE", "/api/v1/documents", {
      body: JSON.stringify({ filename }),
    });

    const data = await response.json();
    return {
      success: data.success ?? false,
      deleted_chunks: data.deleted_chunks ?? 0,
    };
  }
}
