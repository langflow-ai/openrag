/**
 * OpenRAG SDK documents client.
 */

import type { OpenRAGClient } from "./client";
import type { DeleteDocumentResponse, IngestResponse } from "./types";

export interface IngestOptions {
  /** Path to file (Node.js only). */
  filePath?: string;
  /** File object (browser or Node.js). */
  file?: File | Blob;
  /** Filename when providing file/blob. */
  filename?: string;
}

export class DocumentsClient {
  constructor(private client: OpenRAGClient) {}

  /**
   * Ingest a document into the knowledge base.
   *
   * @param options - Ingest options (filePath or file+filename).
   * @returns IngestResponse with document_id and chunk count.
   */
  async ingest(options: IngestOptions): Promise<IngestResponse> {
    const formData = new FormData();

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
    return {
      success: data.success ?? false,
      document_id: data.document_id ?? null,
      filename: data.filename ?? null,
      chunks: data.chunks ?? 0,
    };
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
