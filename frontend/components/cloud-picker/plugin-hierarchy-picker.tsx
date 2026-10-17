"use client";

import { FileText, Folder, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { FileList } from "./file-list";
import type {
  CloudFile,
  ConnectorPickerNode,
  ConnectorPickerPage,
} from "./types";

interface Location {
  id: string | null;
  name: string;
}

export function PluginHierarchyPicker({
  provider,
  connectionId,
  selectedFiles,
  onFileSelected,
  isIngesting,
}: {
  provider: string;
  connectionId: string;
  selectedFiles: CloudFile[];
  onFileSelected: (files: CloudFile[]) => void;
  isIngesting: boolean;
}) {
  const [trail, setTrail] = useState<Location[]>([{ id: null, name: "Root" }]);
  const [nodes, setNodes] = useState<ConnectorPickerNode[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [page, setPage] = useState(0);
  const folder = trail[trail.length - 1];

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ page_size: "100" });
    if (folder.id !== null) params.set("parent_id", folder.id);
    if (cursor !== null) params.set("cursor", cursor);
    setLoading(true);
    setError(null);
    fetch(
      `/api/connectors/${encodeURIComponent(provider)}/${encodeURIComponent(connectionId)}/picker/children?${params}`,
      {
        signal: controller.signal,
      },
    )
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok)
          throw new Error(
            result.error ||
              result.detail ||
              `Unable to load files (${response.status})`,
          );
        return result as ConnectorPickerPage;
      })
      .then((result) => {
        if (!Array.isArray(result.nodes))
          throw new Error("Invalid file listing from connector");
        setNodes((previous) => {
          if (cursor === null) return result.nodes;
          const seen = new Set(previous.map((node) => node.id));
          return [
            ...previous,
            ...result.nodes.filter((node) => {
              if (seen.has(node.id)) return false;
              seen.add(node.id);
              return true;
            }),
          ];
        });
        setPage((current) => current + 1);
        setNextCursor(result.next_cursor ?? null);
      })
      .catch((cause) => {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error ? cause.message : "Unable to load files",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [provider, connectionId, folder.id, cursor, retry]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  function navigate(path: Location[]) {
    setTrail(path);
    setNodes([]);
    setCursor(null);
    setNextCursor(null);
    setPage(0);
    // A navigation to the same folder after paging still needs a fresh first page.
    setRetry((current) => current + 1);
  }

  function toggleFile(node: ConnectorPickerNode) {
    if (isIngesting || node.kind !== "file") return;
    if (selectedFiles.some((file) => file.id === node.id)) {
      onFileSelected(selectedFiles.filter((file) => file.id !== node.id));
    } else {
      onFileSelected([
        ...selectedFiles,
        {
          id: node.id,
          name: node.name,
          size: node.size,
          mimeType: "application/octet-stream",
          modifiedTime: node.modified_time,
        },
      ]);
    }
  }

  return (
    <section aria-label={`${provider} files`} className="space-y-5">
      <nav
        aria-label="Folder path"
        className="flex flex-wrap items-center gap-2 text-sm"
      >
        {trail.map((location, index) => (
          <span
            key={`${location.id ?? "root"}-${index}`}
            className="flex items-center gap-2"
          >
            {index > 0 && <span aria-hidden="true">/</span>}
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={index === trail.length - 1 || isIngesting}
              onClick={() => navigate(trail.slice(0, index + 1))}
            >
              {location.name}
            </Button>
          </span>
        ))}
      </nav>
      <div className="rounded-md border p-3 space-y-1">
        {nodes.map((node) =>
          node.kind === "folder" ? (
            <Button
              key={node.id}
              type="button"
              variant="ghost"
              className="flex w-full justify-start gap-2"
              disabled={isIngesting}
              onClick={() =>
                navigate([...trail, { id: node.id, name: node.name }])
              }
            >
              <Folder className="h-4 w-4" />
              {node.name}
            </Button>
          ) : (
            <label
              key={node.id}
              className="flex items-center gap-3 rounded-md px-3 py-2 hover:bg-muted/30"
            >
              <input
                type="checkbox"
                checked={selectedFiles.some((file) => file.id === node.id)}
                disabled={isIngesting}
                onChange={() => toggleFile(node)}
                aria-label={`Select ${node.name}`}
              />
              <FileText className="h-4 w-4" />
              <span>{node.name}</span>
              {node.is_stale ? (
                <span className="text-xs text-amber-700">Update available</span>
              ) : node.is_ingested ? (
                <span className="text-xs text-muted-foreground">Ingested</span>
              ) : null}
              {typeof node.size === "number" && (
                <span className="ml-auto text-xs text-muted-foreground">
                  {node.size.toLocaleString()} bytes
                </span>
              )}
            </label>
          ),
        )}
        {loading && (
          <p role="status" className="flex items-center gap-2 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading files…
          </p>
        )}
        {error && (
          <div role="alert" className="text-sm text-destructive">
            {error}{" "}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setRetry((current) => current + 1)}
            >
              Retry
            </Button>
          </div>
        )}
        {!loading && !error && nodes.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No files in this folder.
          </p>
        )}
        {nextCursor && !error && (
          <Button
            type="button"
            variant="outline"
            disabled={loading}
            onClick={() => setCursor(nextCursor)}
          >
            Load more
          </Button>
        )}
      </div>
      <FileList
        provider={provider}
        files={selectedFiles}
        onRemoveFile={(id) =>
          onFileSelected(selectedFiles.filter((file) => file.id !== id))
        }
        onClearAll={() => onFileSelected([])}
        shouldDisableActions={isIngesting}
      />
      {page > 1 && (
        <p className="text-xs text-muted-foreground">
          Loaded {page} pages in this folder. Selections remain available while
          browsing.
        </p>
      )}
    </section>
  );
}
