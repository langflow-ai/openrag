import type { File as SearchFile } from "@/app/api/queries/useGetSearchQuery";
import type { TaskFile } from "@/contexts/task-context";

export interface KnowledgeSourceOption {
  value: string;
  label: string;
  count: number;
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
  const sourceCounts = rows
    .filter((file) => (file.status || "active") === "active")
    .reduce((acc, file) => {
      const source = file.filename?.trim() || file.source_url?.trim();
      if (!source) {
        return acc;
      }
      acc.set(source, (acc.get(source) || 0) + 1);
      return acc;
    }, new Map<string, number>());

  return Array.from(sourceCounts.entries())
    .map(([source, count]) => ({
      value: source,
      label: source,
      count,
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}
