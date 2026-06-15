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

/** Lookup keys for matching task overlays to indexed rows (filename, path, basename). */
export function getKnowledgeFileAliasKeys(file?: {
  filename?: string;
  source_url?: string;
}): string[] {
  const keys = new Set<string>();
  const identity = getKnowledgeFileIdentity(file);
  if (identity) {
    keys.add(identity);
  }
  const filename = file?.filename?.trim();
  if (filename) {
    keys.add(filename);
  }
  const sourceUrl = file?.source_url?.trim();
  if (sourceUrl) {
    keys.add(sourceUrl);
    const basename = sourceUrl.split("/").pop()?.trim();
    if (basename) {
      keys.add(basename);
    }
  }
  return [...keys];
}

function taskOverlayPriority(status?: string): number {
  switch (status) {
    case "processing":
      return 3;
    case "failed":
      return 2;
    case "active":
      return 1;
    default:
      return 0;
  }
}

function indexTaskFileOverlays(
  taskFilesAsFiles: SearchFile[],
): Map<string, SearchFile> {
  const map = new Map<string, SearchFile>();
  for (const file of taskFilesAsFiles) {
    for (const key of getKnowledgeFileAliasKeys(file)) {
      const existing = map.get(key);
      if (
        !existing ||
        taskOverlayPriority(file.status) >= taskOverlayPriority(existing.status)
      ) {
        map.set(key, file);
      }
    }
  }
  return map;
}

function lookupTaskFileOverlay(
  map: Map<string, SearchFile>,
  file: SearchFile,
): SearchFile | undefined {
  for (const key of getKnowledgeFileAliasKeys(file)) {
    const match = map.get(key);
    if (match) {
      return match;
    }
  }
  return undefined;
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

  const taskFileMap = indexTaskFileOverlays(taskFilesAsFiles);

  const backendFiles = searchData.map((file) => {
    if (file.connector_type === "openrag_docs") {
      return file;
    }
    const taskFile = lookupTaskFileOverlay(taskFileMap, file);
    if (taskFile) {
      const backendStatus = file.status ?? "active";
      const status =
        taskFile.status === "processing" || taskFile.status === "failed"
          ? taskFile.status
          : backendStatus;
      return {
        ...file,
        filename: taskFile.filename || file.filename,
        source_url: file.source_url || taskFile.source_url,
        connector_type: taskFile.connector_type,
        status,
        error: taskFile.error,
        embedding_model: taskFile.embedding_model ?? file.embedding_model,
        embedding_dimensions:
          taskFile.embedding_dimensions ?? file.embedding_dimensions,
      };
    }
    return file;
  });

  const backendIdentityKeys = new Set<string>();
  for (const file of backendFiles) {
    for (const key of getKnowledgeFileAliasKeys(file)) {
      backendIdentityKeys.add(key);
    }
  }

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
    if (
      getKnowledgeFileAliasKeys(taskFile).some((key) =>
        backendIdentityKeys.has(key),
      )
    ) {
      return false;
    }
    // Keep "active" overlays until the index lists the file (task drops key before refetch).
    return true;
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
