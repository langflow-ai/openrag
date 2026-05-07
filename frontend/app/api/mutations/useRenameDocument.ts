"use client";

import { useMutation } from "@tanstack/react-query";

export interface RenameDocumentRequest {
  current_filename: string;
  new_filename: string;
  document_id?: string | null;
}

export interface RenameDocumentResponse {
  success: boolean;
  /** True when some chunks were renamed but others still use the old filename (HTTP 422). */
  partial?: boolean;
  /** Server resolved or echoed id — persist for Retry after partial rename. */
  document_id?: string | null;
  /** No old-name chunks left; target name already stored for this document_id. */
  idempotent?: boolean;
  /** Renamed using document_id because the UI current name matched no chunks. */
  resumed?: boolean;
  updated_chunks: number;
  remaining_old_chunks?: number;
  matched_chunks?: number;
  old_filename: string;
  new_filename: string;
  error?: string | null;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

const renameDocument = async (
  data: RenameDocumentRequest,
): Promise<RenameDocumentResponse> => {
  const response = await fetch("/api/documents/rename", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      current_filename: data.current_filename,
      new_filename: data.new_filename,
      document_id: data.document_id ?? null,
    }),
  });

  const payload = (await response.json().catch(() => ({}))) as unknown;

  if (
    response.status === 422 &&
    isRecord(payload) &&
    payload.partial === true
  ) {
    return payload as unknown as RenameDocumentResponse;
  }

  if (!response.ok) {
    const rec = isRecord(payload) ? payload : {};
    const message =
      typeof rec.error === "string"
        ? rec.error
        : `Rename failed (${response.status})`;
    throw new Error(message);
  }

  return payload as unknown as RenameDocumentResponse;
};

export const useRenameDocument = () => {
  return useMutation({
    mutationFn: renameDocument,
  });
};
