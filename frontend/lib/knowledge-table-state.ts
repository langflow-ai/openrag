import type { File as SearchFile } from "@/app/api/queries/useGetSearchQuery";
import type { TaskFile } from "@/contexts/task-context";

export interface KnowledgeSourceOption {
  /** `document_id` when present, else filename/URL (multiselect value). */
  value: string;
  label: string;
  count: number;
  documentId?: string;
}

/** Value for POST /documents/rename `current_filename` (indexed field), not the grid grouping key. */
export function getRenameCurrentFilename(
  file: Pick<SearchFile, "filename" | "chunks">,
): string {
  const fromChunk = file.chunks?.[0]?.filename?.trim();
  if (fromChunk) {
    return fromChunk;
  }
  return (file.filename || "").trim();
}

export function getKnowledgeFileIdentity(file?: {
  filename?: string;
  source_url?: string;
}) {
  if (!file) {
    return "";
  }

  const normalizedFilename = file.filename?.trim();
  if (normalizedFilename) {
    return normalizedFilename;
  }

  const normalizedSourceUrl = file.source_url?.trim();
  if (normalizedSourceUrl) {
    return normalizedSourceUrl;
  }

  return "";
}

export function buildKnowledgeTableRows(
  searchData: SearchFile[],
  taskFiles: TaskFile[],
  hasActiveFilter = false,
): SearchFile[] {
  const taskFilesAsFiles: SearchFile[] = taskFiles.map((taskFile) => {
    const normalizedFilename =
      taskFile.filename?.trim() ||
      taskFile.source_url?.trim() ||
      "Untitled source";

    return {
      filename: normalizedFilename,
      mimetype: taskFile.mimetype,
      source_url: taskFile.source_url || "",
      size: taskFile.size,
      connector_type: taskFile.connector_type,
      status: taskFile.status,
      error: taskFile.error,
      embedding_model: taskFile.embedding_model,
      embedding_dimensions: taskFile.embedding_dimensions,
    };
  });

  const taskFileMap = new Map(
    taskFilesAsFiles.map((file) => [getKnowledgeFileIdentity(file), file]),
  );

  const backendFiles = searchData.map((file) => {
    if (file.connector_type === "openrag_docs") {
      return file;
    }
    const taskFile = taskFileMap.get(getKnowledgeFileIdentity(file));
    if (taskFile) {
      const backendStatus = file.status ?? "active";
      return { ...file, ...taskFile, status: backendStatus };
    }
    return file;
  });

  const filteredTaskFiles = taskFilesAsFiles.filter((taskFile) => {
    if (
      taskFile.filename === "OpenRAG docs refresh" ||
      taskFile.source_url.includes("openr.ag")
    ) {
      return false;
    }
    if (taskFile.connector_type === "openrag_docs") {
      return false;
    }
    return (
      taskFile.status !== "active" &&
      !backendFiles.some(
        (backendFile) =>
          getKnowledgeFileIdentity(backendFile) ===
          getKnowledgeFileIdentity(taskFile),
      )
    );
  });

  if (hasActiveFilter) {
    return backendFiles;
  }

  return [...backendFiles, ...filteredTaskFiles];
}

export function buildActiveSourceOptions(
  rows: SearchFile[],
): KnowledgeSourceOption[] {
  const byValue = new Map<
    string,
    { label: string; count: number; documentId?: string }
  >();
  for (const file of rows.filter((f) => (f.status || "active") === "active")) {
    const label = file.filename?.trim() || file.source_url?.trim();
    if (!label) {
      continue;
    }
    const id = file.document_id?.trim();
    const value = id || label;
    const cur = byValue.get(value);
    if (cur) {
      cur.count += 1;
      if (!cur.documentId && id) {
        cur.documentId = id;
      }
    } else {
      byValue.set(value, { label, count: 1, documentId: id });
    }
  }

  return Array.from(byValue.entries())
    .map(([value, { label, count, documentId }]) => ({
      value,
      label,
      count,
      documentId,
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}
