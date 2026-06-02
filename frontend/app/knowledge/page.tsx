"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  type CheckboxSelectionCallbackParams,
  type ColDef,
  type GetRowIdParams,
  themeQuartz,
  type ValueFormatterParams,
  type ValueGetterParams,
} from "ag-grid-community";
import { AgGridReact, type CustomCellRendererProps } from "ag-grid-react";
import { AlertTriangle, Cloud, FileIcon, Globe, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { KnowledgeDropdown } from "@/components/knowledge-dropdown";
import { ProtectedRoute } from "@/components/protected-route";
import { Banner, BannerIcon, BannerTitle } from "@/components/ui/banner";
import { Button } from "@/components/ui/button";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useTask } from "@/contexts/task-context";
import {
  EMPTY_SEARCH_RESULT,
  type File,
  type SearchResult,
  useGetSearchQuery,
} from "../api/queries/useGetSearchQuery";
import { useListFiles } from "../api/queries/useListFiles";
import "@/components/AgGrid/registerAgGridModules";
import "@/components/AgGrid/agGridStyles.css";
import { toast } from "sonner";
import { KnowledgeActionsDropdown } from "@/components/knowledge-actions-dropdown";
import { KnowledgeBatchActionsBar } from "@/components/knowledge-batch-actions-bar";
import { KnowledgeSearchBar } from "@/components/knowledge-search-bar";
import { KnowledgeSearchInput } from "@/components/knowledge-search-input";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { getConnectorDescriptor } from "@/lib/connectors/registry";
import {
  buildKnowledgeTableRows,
  getKnowledgeFileIdentity,
} from "@/lib/knowledge-table-state";
import { parseTimestampMs } from "@/lib/time-utils";
import { cn } from "@/lib/utils";
import {
  DeleteConfirmationDialog,
  formatFilesToDelete,
} from "../../components/delete-confirmation-dialog";
import { SyncConfirmDialog } from "../../components/sync-confirm-dialog";
import { useDeleteDocument } from "../api/mutations/useDeleteDocument";
import { useRefreshOpenragDocs } from "../api/mutations/useRefreshOpenragDocs";
import {
  type SyncAllPreviewResponse,
  useSyncAllConnectors,
  useSyncAllConnectorsPreview,
} from "../api/mutations/useSyncConnector";

function sameFileSelection(a: File[], b: File[]): boolean {
  if (a.length !== b.length) {
    return false;
  }
  const identities = new Set(b.map((row) => getKnowledgeFileIdentity(row)));
  return a.every((row) => identities.has(getKnowledgeFileIdentity(row)));
}

/** Failed overlays can stay selected after they lose their checkbox (processing → failed). */
function syncGridSelectionToDeletableRows(
  api: NonNullable<AgGridReact<File>["api"]>,
  isDeletable: (file?: File) => boolean,
): File[] {
  api.forEachNode((node) => {
    if (node.isSelected() && !isDeletable(node.data)) {
      node.setSelected(false);
    }
  });
  return api.getSelectedRows().filter(isDeletable);
}

/** Deselect non-deletable rows in the grid only; returns whether anything changed. */
function pruneNonDeletableGridSelection(
  api: NonNullable<AgGridReact<File>["api"]>,
  isDeletable: (file?: File) => boolean,
): boolean {
  let pruned = false;
  api.forEachNode((node) => {
    if (node.isSelected() && !isDeletable(node.data)) {
      node.setSelected(false);
      pruned = true;
    }
  });
  return pruned;
}

/** List-files uses term filters; "*" means "any" in the UI — do not send it literally. */
function listFilesFilterParam(values?: string[]): string | undefined {
  const raw = values?.[0]?.trim();
  if (!raw || raw === "*") {
    return undefined;
  }
  return raw;
}

// Function to get the appropriate icon for a connector type
function getSourceIcon(connectorType?: string) {
  if (connectorType) {
    const Icon = getConnectorDescriptor(connectorType)?.Icon;
    if (Icon) return <Icon className="h-4 w-4 text-foreground flex-shrink-0" />;
  }
  switch (connectorType) {
    case "openrag_docs":
    case "url":
      return <Globe className="h-4 w-4 text-muted-foreground flex-shrink-0" />;
    case "s3":
      return <Cloud className="h-4 w-4 text-foreground flex-shrink-0" />;
    default:
      return (
        <FileIcon className="h-4 w-4 text-muted-foreground flex-shrink-0" />
      );
  }
}

function SearchPage() {
  const isCloudBrand = useIsCloudBrand();
  const queryClient = useQueryClient();
  const router = useRouter();
  const {
    files: taskFiles,
    tasks,
    refreshTasks,
    openMenu,
    setRecentTasksExpanded,
    selectTask,
  } = useTask();
  const { parsedFilterData, queryOverride, selectedFilter } =
    useKnowledgeFilter();
  const [selectedRows, setSelectedRows] = useState<File[]>([]);
  const [showBulkDeleteDialog, setShowBulkDeleteDialog] = useState(false);
  const lastErrorRef = useRef<string | null>(null);
  const hasInitializedFailedFilesRef = useRef(false);
  const seenFailedFileKeysRef = useRef<Set<string>>(new Set());

  const deleteDocumentMutation = useDeleteDocument();
  const syncAllConnectorsMutation = useSyncAllConnectors();
  const syncAllPreviewMutation = useSyncAllConnectorsPreview();
  const refreshOpenragDocsMutation = useRefreshOpenragDocs();
  const [syncDialogOpen, setSyncDialogOpen] = useState(false);
  const [syncPreview, setSyncPreview] = useState<SyncAllPreviewResponse | null>(
    null,
  );

  const handleOpenSyncDialog = useCallback(async () => {
    setSyncPreview(null);
    setSyncDialogOpen(true);
    try {
      const preview = await syncAllPreviewMutation.mutateAsync();
      setSyncPreview(preview);
    } catch (error) {
      setSyncDialogOpen(false);
      toast.error(
        error instanceof Error ? error.message : "Failed to preview sync",
      );
    }
  }, [syncAllPreviewMutation]);

  const handleConfirmSync = useCallback(async () => {
    try {
      const result = await syncAllConnectorsMutation.mutateAsync();
      if (result.status === "no_files") {
        toast.info(
          result.message ||
            "No cloud files to sync. Add files from cloud connectors first.",
        );
      } else if (
        result.synced_connectors &&
        result.synced_connectors.length > 0
      ) {
        toast.success(
          `Sync started for ${result.synced_connectors.join(", ")}. Check task notifications for progress.`,
        );
      } else if (result.errors && result.errors.length > 0) {
        toast.error("Some connectors failed to sync");
      }
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to sync connectors",
      );
    }
  }, [syncAllConnectorsMutation]);

  useEffect(() => {
    refreshTasks();
  }, [refreshTasks]);

  const getFailedFileKey = useCallback(
    (file: (typeof taskFiles)[number]) =>
      `${file.task_id}:${file.source_url || file.filename}`,
    [],
  );

  const getTaskIdForRow = useCallback(
    (file?: File): string | null => {
      if (!file) return null;
      const sourceUrl = file.source_url || "";
      const filename = file.filename || "";
      const matches = taskFiles.filter(
        (taskFile) =>
          (sourceUrl && taskFile.source_url === sourceUrl) ||
          taskFile.filename === filename,
      );
      if (matches.length === 0) return null;

      const failedMatches =
        file.status === "failed"
          ? matches.filter((taskFile) => taskFile.status === "failed")
          : matches;
      const candidates = failedMatches.length > 0 ? failedMatches : matches;

      const taskTimestampMsById = new Map(
        tasks.map((task) => [
          task.task_id,
          parseTimestampMs(task.updated_at) ??
            parseTimestampMs(task.created_at) ??
            0,
        ]),
      );

      const mostRecent = [...candidates].sort((a, b) => {
        const aMs =
          taskTimestampMsById.get(a.task_id) ??
          parseTimestampMs(a.updated_at) ??
          parseTimestampMs(a.created_at) ??
          0;
        const bMs =
          taskTimestampMsById.get(b.task_id) ??
          parseTimestampMs(b.updated_at) ??
          parseTimestampMs(b.created_at) ??
          0;
        return bMs - aMs;
      })[0];

      return mostRecent?.task_id || null;
    },
    [taskFiles, tasks],
  );

  // Auto-open unified task panel only when a NEW task file transitions to failed
  // (skip initial failed files that already existed on page load).
  useEffect(() => {
    const failedFiles = taskFiles.filter((file) => file.status === "failed");
    const seenKeys = seenFailedFileKeysRef.current;

    if (!hasInitializedFailedFilesRef.current) {
      failedFiles.forEach((file) => {
        seenKeys.add(getFailedFileKey(file));
      });
      hasInitializedFailedFilesRef.current = true;
      return;
    }

    let firstNewFailureTaskId: string | null = null;
    const hasNewFailure = failedFiles.some((file) => {
      const key = getFailedFileKey(file);
      if (seenKeys.has(key)) {
        return false;
      }
      seenKeys.add(key);
      if (!firstNewFailureTaskId) {
        firstNewFailureTaskId = file.task_id;
      }
      return true;
    });

    if (hasNewFailure) {
      if (firstNewFailureTaskId) {
        selectTask(firstNewFailureTaskId);
      }
      openMenu();
      setRecentTasksExpanded(true);
    }
  }, [
    taskFiles,
    openMenu,
    setRecentTasksExpanded,
    selectTask,
    getFailedFileKey,
  ]);

  // Use server-side file listing for default/wildcard view; search otherwise.
  // Wildcard follows bar text or saved filter query (bar is cleared when a filter is picked).
  const effectiveSearchText =
    queryOverride.trim() || parsedFilterData?.query?.trim() || "";
  const isWildcardQuery =
    effectiveSearchText === "" || effectiveSearchText === "*";

  const {
    data: listFilesData,
    isLoading: isListFilesLoading,
    error: listFilesError,
    isError: isListFilesError,
  } = useListFiles(
    {
      pageSize: 100,
      search: isWildcardQuery ? undefined : queryOverride,
      connectorType: listFilesFilterParam(
        parsedFilterData?.filters?.connector_types,
      ),
      mimetype: listFilesFilterParam(parsedFilterData?.filters?.document_types),
      owner: listFilesFilterParam(parsedFilterData?.filters?.owners),
    },
    {
      refetchInterval: 5000,
      enabled: isWildcardQuery,
    },
  );

  const {
    data: searchData = EMPTY_SEARCH_RESULT,
    isLoading: isSearchLoading,
    error: searchError,
    isError: isSearchError,
  } = useGetSearchQuery(queryOverride, parsedFilterData, {
    enabled: !isWildcardQuery,
  });

  const { files: searchFiles, warnings: searchWarnings } =
    searchData as SearchResult;

  // Merge data from whichever source is active
  const effectiveData: File[] = isWildcardQuery
    ? (listFilesData?.files ?? [])
    : searchFiles;
  const isLoading = isWildcardQuery ? isListFilesLoading : isSearchLoading;
  const error = isWildcardQuery ? listFilesError : searchError;
  const isError = isWildcardQuery ? isListFilesError : isSearchError;

  const isOpenragDocsRow = useCallback((file?: File) => {
    return (
      file?.connector_type === "openrag_docs" ||
      file?.connector_type === "system_default"
    );
  }, []);

  const getFileIdentity = useCallback((file?: File) => {
    return getKnowledgeFileIdentity(file);
  }, []);

  const isDeletableKnowledgeRow = useCallback((file?: File) => {
    return (file?.status || "active") === "active";
  }, []);

  const resolveDeleteFilename = useCallback(
    (row: File) => {
      const identity = getKnowledgeFileIdentity(row);
      const indexed = effectiveData.find(
        (file) => getKnowledgeFileIdentity(file) === identity,
      );
      return indexed?.filename ?? row.filename;
    },
    [effectiveData],
  );

  const getOwnerLabel = useCallback((file?: File): string => {
    return file?.owner_name?.trim() || file?.owner_email?.trim() || "—";
  }, []);

  const normalizeSourceForSort = useCallback((value?: string): string => {
    const trimmed = (value || "").trim();
    if (!trimmed) {
      return "";
    }

    try {
      const parsed = new URL(trimmed);
      const hostname = parsed.hostname.toLowerCase();
      const pathname = parsed.pathname.replace(/\/+$/, "").toLowerCase();
      return `${hostname}${pathname}`;
    } catch {
      return trimmed
        .toLowerCase()
        .replace(/^https?:\/\//, "")
        .split(/[?#]/)[0]
        .replace(/\/+$/, "");
    }
  }, []);

  const getStatusSortRank = useCallback((status?: File["status"]): number => {
    switch (status) {
      case "active":
        return 0;
      case "processing":
        return 1;
      case "sync":
        return 2;
      case "failed":
        return 3;
      case "unavailable":
        return 4;
      case "hidden":
        return 5;
      default:
        return 0;
    }
  }, []);

  const hasOpenragRefreshCueFromTasks = tasks.some((task) => {
    const isTaskActive =
      task.status === "pending" ||
      task.status === "running" ||
      task.status === "processing";
    if (!isTaskActive || !task.files) {
      return false;
    }

    return Object.entries(task.files).some(([fileKey, fileInfo]) => {
      const filename = (fileInfo as { filename?: string })?.filename ?? "";
      return (
        filename === "OpenRAG docs refresh" || fileKey.includes("openr.ag")
      );
    });
  });
  const hasOpenragRefreshCue =
    refreshOpenragDocsMutation.isPending || hasOpenragRefreshCueFromTasks;

  // Show toast notification for search errors
  useEffect(() => {
    if (isError && error) {
      const errorMessage =
        error instanceof Error ? error.message : "Search failed";
      // Avoid showing duplicate toasts for the same error
      if (lastErrorRef.current !== errorMessage) {
        lastErrorRef.current = errorMessage;
        toast.error("Search error", {
          description: errorMessage,
          duration: 5000,
        });
      }
    } else if (!isError) {
      // Reset when query succeeds
      lastErrorRef.current = null;
    }
  }, [isError, error]);
  // Third arg: saved filter only — draft `parsedFilterData` (create mode) must still show task rows.
  const fileResults = buildKnowledgeTableRows(
    effectiveData,
    taskFiles,
    Boolean(selectedFilter),
  );

  const gridRows = fileResults;
  const gridRef = useRef<AgGridReact>(null);

  // Re-run only when row identity/status changes, not on every list poll reference.
  const gridRowsSelectionKey = useMemo(
    () =>
      gridRows
        .map(
          (row) => `${getKnowledgeFileIdentity(row)}:${row.status ?? "active"}`,
        )
        .join("\0"),
    [gridRows],
  );

  useEffect(() => {
    const api = gridRef.current?.api;
    if (!api) {
      return;
    }
    pruneNonDeletableGridSelection(api, isDeletableKnowledgeRow);
    const nextSelected = api.getSelectedRows().filter(isDeletableKnowledgeRow);
    setSelectedRows((current) =>
      sameFileSelection(current, nextSelected) ? current : nextSelected,
    );
  }, [gridRowsSelectionKey, isDeletableKnowledgeRow]);

  const columnDefs: ColDef<File>[] = [
    {
      field: "filename",
      headerName: "Source",
      sortable: true,
      comparator: (valueA?: string, valueB?: string) => {
        const sourceA = normalizeSourceForSort(valueA);
        const sourceB = normalizeSourceForSort(valueB);
        if (sourceA === sourceB) {
          const fallbackA = (valueA || "").trim().toLowerCase();
          const fallbackB = (valueB || "").trim().toLowerCase();
          if (fallbackA === fallbackB) {
            return 0;
          }
          return fallbackA < fallbackB ? -1 : 1;
        }
        return sourceA < sourceB ? -1 : 1;
      },
      checkboxSelection: (params: CheckboxSelectionCallbackParams<File>) =>
        isDeletableKnowledgeRow(params?.data),
      headerCheckboxSelection: true,
      ...(isCloudBrand
        ? { flex: 2.2, minWidth: 260 }
        : { initialFlex: 2, minWidth: 220 }),
      cellRenderer: ({ data, value }: CustomCellRendererProps<File>) => {
        const status = data?.status || "active";
        const isActive = status === "active";
        const showOpenragSourceAnimation =
          isOpenragDocsRow(data) && hasOpenragRefreshCue;
        return (
          <div className="flex items-center overflow-hidden w-full min-w-0 h-full">
            <div
              className={`transition-opacity duration-200 ${
                isActive ? "w-0" : "w-7"
              }`}
            ></div>
            <button
              type="button"
              className={cn(
                "flex items-center gap-2 text-left flex-1 overflow-hidden transition-colors",
                isActive
                  ? isCloudBrand
                    ? "cursor-pointer hover:text-primary"
                    : "cursor-pointer hover:text-blue-600"
                  : "cursor-default",
              )}
              onClick={() => {
                if (!isActive) return;
                router.push(
                  `/knowledge/chunks?filename=${encodeURIComponent(
                    data?.filename ?? "",
                  )}`,
                );
              }}
            >
              {getSourceIcon(data?.connector_type)}
              <Tooltip>
                <TooltipTrigger asChild>
                  <span
                    className={cn(
                      "font-medium truncate min-w-0",
                      showOpenragSourceAnimation
                        ? "text-primary animate-pulse"
                        : "text-foreground",
                    )}
                  >
                    {value}
                  </span>
                </TooltipTrigger>
                <TooltipContent side="top" align="start">
                  {value}
                </TooltipContent>
              </Tooltip>
            </button>
          </div>
        );
      },
    },
    {
      field: "size",
      headerName: "Size",
      ...(isCloudBrand ? { flex: 1, minWidth: 110 } : {}),
      sortable: true,
      comparator: (valueA?: number, valueB?: number) =>
        (valueA || 0) - (valueB || 0),
      valueFormatter: (params: ValueFormatterParams<File>) =>
        params.value ? `${Math.round(params.value / 1024)} KB` : "-",
      cellClass: isCloudBrand ? "text-muted-foreground" : undefined,
    },
    {
      field: "mimetype",
      headerName: "Type",
      ...(isCloudBrand ? { flex: 1, minWidth: 110 } : {}),
      cellClass: isCloudBrand ? "text-muted-foreground" : undefined,
      sortable: true,
    },
    {
      field: "owner",
      headerName: "Owner",
      ...(isCloudBrand ? { flex: 1.4, minWidth: 180 } : {}),
      valueFormatter: (params: ValueFormatterParams<File>) =>
        params.data?.owner_name || params.data?.owner_email || "—",
      cellClass: isCloudBrand ? "text-muted-foreground" : undefined,
      sortable: true,
      valueGetter: (params: ValueGetterParams<File>) =>
        getOwnerLabel(params.data),
      comparator: (valueA?: string, valueB?: string) =>
        (valueA || "—").localeCompare(valueB || "—", undefined, {
          sensitivity: "base",
        }),
    },
    {
      field: "chunkCount",
      headerName: "Chunks",
      ...(isCloudBrand ? { flex: 0.9, minWidth: 95 } : {}),
      sortable: true,
      comparator: (valueA?: number, valueB?: number) =>
        (valueA || 0) - (valueB || 0),
      valueFormatter: (params: ValueFormatterParams<File>) =>
        params.data?.chunkCount?.toString() || "-",
      cellClass: isCloudBrand ? "text-muted-foreground" : undefined,
    },
    {
      field: "avgScore",
      headerName: "Avg score",
      ...(isCloudBrand ? { flex: 1, minWidth: 120 } : {}),
      sortable: true,
      comparator: (valueA?: number, valueB?: number) =>
        (valueA || 0) - (valueB || 0),
      cellRenderer: ({ value }: CustomCellRendererProps<File>) => {
        if (isCloudBrand) {
          return (
            <span className="text-muted-foreground">
              {typeof value === "number" ? value.toFixed(2) : "-"}
            </span>
          );
        }
        return (
          <span className="text-xs text-accent-emerald-foreground bg-accent-emerald px-2 py-1 rounded">
            {value?.toFixed(2) ?? "-"}
          </span>
        );
      },
    },
    {
      field: "embedding_model",
      headerName: "Embedding model",
      ...(isCloudBrand ? { flex: 1.4 } : {}),
      sortable: true,
      minWidth: 200,
      cellRenderer: ({ data }: CustomCellRendererProps<File>) => (
        <span className="text-xs text-muted-foreground">
          {data?.embedding_model || "—"}
        </span>
      ),
    },
    {
      field: "embedding_dimensions",
      headerName: "Dimensions",
      ...(isCloudBrand ? { flex: 0.9, minWidth: 110 } : { width: 110 }),
      sortable: true,
      comparator: (valueA?: number, valueB?: number) =>
        (valueA || 0) - (valueB || 0),
      cellRenderer: ({ data }: CustomCellRendererProps<File>) => (
        <span className="text-xs text-muted-foreground">
          {typeof data?.embedding_dimensions === "number"
            ? data.embedding_dimensions.toString()
            : "—"}
        </span>
      ),
    },
    {
      field: "status",
      headerName: "Status",
      ...(isCloudBrand ? { flex: 1, minWidth: 130 } : {}),
      sortable: true,
      valueGetter: (params: ValueGetterParams<File>) =>
        params.data?.status || "active",
      comparator: (valueA?: File["status"], valueB?: File["status"]) =>
        getStatusSortRank(valueA) - getStatusSortRank(valueB),
      cellRenderer: ({ data }: CustomCellRendererProps<File>) => {
        const status = data?.status || "active";
        const showOpenragRefreshCue =
          isOpenragDocsRow(data) && hasOpenragRefreshCue;

        if (showOpenragRefreshCue) {
          if (isCloudBrand) {
            return (
              <div className="inline-flex items-center gap-2 text-primary">
                <RefreshCw className="h-4 w-4 animate-spin" />
                <span className="text-sm font-medium">Refreshing</span>
              </div>
            );
          }
          return (
            <div className="inline-flex items-center justify-center h-5 w-5">
              <RefreshCw
                className="h-4 w-4 text-primary animate-spin"
                aria-label="OpenRAG doc is refreshing"
              />
            </div>
          );
        }

        if (status === "failed") {
          return (
            <button
              type="button"
              className={cn(
                "inline-flex items-center h-full transition",
                isCloudBrand
                  ? "text-destructive hover:opacity-80"
                  : "w-full text-red-500 hover:text-red-400",
              )}
              aria-label="View ingestion error"
              data-testid="failed-status-cell-trigger"
              onClick={() => {
                selectTask(getTaskIdForRow(data));
                openMenu();
                setRecentTasksExpanded(true);
              }}
            >
              <StatusBadge status={status} className="pointer-events-none" />
            </button>
          );
        }

        return <StatusBadge status={status} />;
      },
    },
    {
      colId: "actions",
      headerName: "",
      width: isCloudBrand ? 56 : 40,
      minWidth: isCloudBrand ? 56 : 0,
      ...(isCloudBrand ? { maxWidth: 56 } : { initialFlex: 0 }),
      sortable: false,
      filter: false,
      resizable: false,
      suppressMovable: true,
      cellRenderer: ({ data }: CustomCellRendererProps<File>) => {
        const status = data?.status || "active";
        if (status !== "active") return null;
        return (
          <KnowledgeActionsDropdown
            filename={data?.filename || ""}
            connectorType={data?.connector_type}
          />
        );
      },
      cellStyle: {
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 0,
      },
    },
  ];

  const defaultColDef: ColDef<File> = {
    resizable: false,
    suppressMovable: true,
    ...(isCloudBrand ? { sortable: false } : {}),
    initialFlex: 1,
    minWidth: 100,
  };

  const onSelectionChanged = useCallback(() => {
    if (!gridRef.current) {
      return;
    }
    const nextSelected = syncGridSelectionToDeletableRows(
      gridRef.current.api,
      isDeletableKnowledgeRow,
    );
    setSelectedRows((current) =>
      sameFileSelection(current, nextSelected) ? current : nextSelected,
    );
  }, [isDeletableKnowledgeRow]);

  const handleBulkDelete = async () => {
    const rowsToDelete = selectedRows.filter(isDeletableKnowledgeRow);
    if (rowsToDelete.length === 0) return;

    try {
      const deleteResults = await Promise.allSettled(
        rowsToDelete.map((row) =>
          deleteDocumentMutation.mutateAsync({
            filename: resolveDeleteFilename(row),
          }),
        ),
      );

      await refreshTasks();
      await queryClient.invalidateQueries({ queryKey: ["search"] });
      await queryClient.invalidateQueries({ queryKey: ["listFiles"] });
      await queryClient.refetchQueries({ queryKey: ["search"] });
      await queryClient.refetchQueries({ queryKey: ["listFiles"] });

      const deleted = deleteResults.filter(
        (
          result,
        ): result is PromiseFulfilledResult<
          Awaited<ReturnType<typeof deleteDocumentMutation.mutateAsync>>
        > =>
          result.status === "fulfilled" &&
          (result.value.deleted_chunks || 0) > 0,
      );
      const noChunks = deleteResults.filter(
        (result) =>
          result.status === "fulfilled" &&
          (result.value.deleted_chunks || 0) === 0,
      );
      const failed = deleteResults.filter(
        (result): result is PromiseRejectedResult =>
          result.status === "rejected",
      );

      if (deleted.length > 0) {
        toast.success(
          `Deleted ${deleted.length} document${deleted.length > 1 ? "s" : ""}`,
        );
      } else if (failed.length === 0) {
        toast.warning(
          "No document chunks were deleted. Files may be missing or not deletable in your current context.",
        );
      }

      if (noChunks.length > 0 && deleted.length > 0) {
        toast.warning(
          `${noChunks.length} selected file${noChunks.length > 1 ? "s had" : " had"} no matching chunks.`,
        );
      }

      if (failed.length > 0) {
        toast.error(
          `${failed.length} document${failed.length > 1 ? "s" : ""} could not be deleted`,
          {
            description:
              failed[0].reason instanceof Error
                ? failed[0].reason.message
                : undefined,
          },
        );
      }
      setSelectedRows([]);
      setShowBulkDeleteDialog(false);

      // Clear selection in the grid
      if (gridRef.current) {
        gridRef.current.api.deselectAll();
      }
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "Failed to delete some documents",
      );
      setShowBulkDeleteDialog(false);
    }
  };

  // enables pagination in the grid
  const pagination = true;

  // sets 25 rows per page (default is 100)
  const paginationPageSize = 25;

  // allows the user to select the page size from a predefined list of page sizes
  const paginationPageSizeSelector = [10, 25, 50, 100];

  return (
    <>
      <div className="flex flex-col h-full">
        <div className="flex items-center justify-between mb-6">
          <h2
            className={cn(
              "text-lg font-semibold",
              isCloudBrand && "ibm-section-title",
            )}
          >
            Project knowledge
          </h2>
        </div>
        {isCloudBrand ? (
          <div className="relative overflow-hidden h-12 shrink-0">
            <div
              className={cn(
                "transition-transform duration-200 ease-in-out",
                selectedRows.length > 0
                  ? "-translate-y-full pointer-events-none select-none"
                  : "translate-y-0",
              )}
            >
              <KnowledgeSearchBar />
            </div>
            <div
              className={cn(
                "absolute top-0 left-0 right-0 h-12 transition-transform duration-200 ease-in-out",
                selectedRows.length > 0
                  ? "translate-y-0"
                  : "translate-y-full pointer-events-none select-none",
              )}
            >
              <KnowledgeBatchActionsBar
                selectedCount={selectedRows.length}
                onDelete={() => setShowBulkDeleteDialog(true)}
                onCancel={() => {
                  setSelectedRows([]);
                  gridRef.current?.api.deselectAll();
                }}
              />
            </div>
          </div>
        ) : (
          /* Search Input Area */
          <div className="flex-1 flex items-center flex-shrink-0 flex-wrap-reverse gap-3 mb-6">
            <KnowledgeSearchInput />

            <Button
              type="button"
              variant="outline"
              className="rounded-lg flex-shrink-0"
              disabled={
                syncAllConnectorsMutation.isPending ||
                syncAllPreviewMutation.isPending
              }
              onClick={handleOpenSyncDialog}
            >
              {syncAllConnectorsMutation.isPending ||
              syncAllPreviewMutation.isPending ? (
                <>
                  <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                  Syncing...
                </>
              ) : (
                <>
                  <RefreshCw className="h-4 w-4 mr-2" />
                  Sync
                </>
              )}
            </Button>
            <Button
              type="button"
              variant="outline"
              className="rounded-lg flex-shrink-0"
              disabled={refreshOpenragDocsMutation.isPending}
              onClick={async () => {
                try {
                  toast.info("Refreshing OpenRAG docs...");
                  const result = await refreshOpenragDocsMutation.mutateAsync();
                  toast.success(result.message);
                } catch (error) {
                  toast.error(
                    error instanceof Error
                      ? error.message
                      : "Failed to refresh OpenRAG docs",
                  );
                }
              }}
            >
              {refreshOpenragDocsMutation.isPending ? (
                <>Refreshing docs...</>
              ) : (
                <>Fetch latest docs</>
              )}
            </Button>
            {selectedRows.length > 0 && (
              <Button
                type="button"
                variant="destructive"
                className="rounded-lg flex-shrink-0"
                onClick={() => setShowBulkDeleteDialog(true)}
              >
                Delete
              </Button>
            )}
            <div className="ml-auto">
              <KnowledgeDropdown />
            </div>
          </div>
        )}
        {!isWildcardQuery && searchWarnings.length > 0 && (
          <div className="mb-4 flex flex-col gap-2">
            {searchWarnings.map((warning, idx) => {
              const isEmbeddingWarning =
                warning.code === "embedding_unavailable";
              const semanticDown =
                isEmbeddingWarning &&
                warning.semantic_search_available === false;
              const title = isEmbeddingWarning
                ? semanticDown
                  ? "Semantic search degraded — keyword results only"
                  : "Semantic search partially degraded"
                : warning.message || "Search warning";
              const details =
                warning.models && warning.models.length > 0
                  ? ` Affected embedding model${warning.models.length > 1 ? "s" : ""}: ${warning.models.join(", ")}.`
                  : "";
              return (
                <Banner
                  key={`${warning.code}-${idx}`}
                  inset
                  className="bg-amber-500/10 text-amber-100 border border-amber-500/30"
                >
                  <BannerIcon icon={AlertTriangle} />
                  <BannerTitle>
                    <span className="font-medium">{title}.</span>
                    <span className="ml-1 opacity-90">
                      {isEmbeddingWarning
                        ? `The provider for some indexed documents is no longer reachable, so results rely on keyword matching.${details} Re-configure the provider or re-ingest those documents with another embedding model to restore semantic search.`
                        : warning.message}
                    </span>
                  </BannerTitle>
                </Banner>
              );
            })}
          </div>
        )}
        {isCloudBrand ? (
          <AgGridReact
            className="w-full overflow-auto border"
            columnDefs={columnDefs as ColDef<File>[]}
            defaultColDef={defaultColDef}
            loading={isLoading || deleteDocumentMutation.isPending}
            ref={gridRef}
            theme={themeQuartz.withParams({ browserColorScheme: "inherit" })}
            rowData={gridRows}
            rowSelection="multiple"
            getRowId={(params: GetRowIdParams<File>) =>
              getFileIdentity(params.data)
            }
            isRowSelectable={(params) => isDeletableKnowledgeRow(params.data)}
            domLayout="normal"
            onSelectionChanged={onSelectionChanged}
            pagination={pagination}
            paginationPageSize={paginationPageSize}
            paginationPageSizeSelector={paginationPageSizeSelector}
            headerHeight={64}
            rowHeight={64}
            noRowsOverlayComponent={() => (
              <div className="text-center pb-[45px]">
                <div className="text-lg text-primary font-semibold">
                  No knowledge
                </div>
                <div className="text-sm mt-1 text-muted-foreground">
                  Add files from local or your preferred cloud.
                </div>
              </div>
            )}
          />
        ) : (
          <AgGridReact
            className="w-full overflow-auto"
            columnDefs={columnDefs as ColDef<File>[]}
            defaultColDef={defaultColDef}
            loading={isLoading || deleteDocumentMutation.isPending}
            ref={gridRef}
            theme={themeQuartz.withParams({ browserColorScheme: "inherit" })}
            rowData={gridRows}
            rowSelection="multiple"
            rowMultiSelectWithClick={false}
            suppressRowClickSelection={true}
            getRowId={(params: GetRowIdParams<File>) =>
              getFileIdentity(params.data)
            }
            isRowSelectable={(params) => isDeletableKnowledgeRow(params.data)}
            domLayout="normal"
            onSelectionChanged={onSelectionChanged}
            pagination={pagination}
            paginationPageSize={paginationPageSize}
            paginationPageSizeSelector={paginationPageSizeSelector}
            noRowsOverlayComponent={() => (
              <div className="text-center pb-[45px]">
                <div className="text-lg text-primary font-semibold">
                  No knowledge
                </div>
                <div className="text-sm mt-1 text-muted-foreground">
                  Add files from local or your preferred cloud.
                </div>
              </div>
            )}
          />
        )}
      </div>

      {/* Bulk Delete Confirmation Dialog */}
      <DeleteConfirmationDialog
        open={showBulkDeleteDialog}
        onOpenChange={setShowBulkDeleteDialog}
        title={selectedRows.length > 1 ? "Delete documents" : "Delete document"}
        description={`Are you sure you want to delete ${selectedRows.length} document${selectedRows.length > 1 ? "s" : ""}?`}
        confirmText={selectedRows.length > 1 ? "Delete all" : "Delete"}
        onConfirm={handleBulkDelete}
        isLoading={deleteDocumentMutation.isPending}
      >
        <p className="my-2">
          This will remove all chunks and data associated with these documents.
          This action cannot be undone.
        </p>
        <p className="my-2">Documents to be deleted:</p>
        {formatFilesToDelete(selectedRows)}
      </DeleteConfirmationDialog>

      <SyncConfirmDialog
        open={syncDialogOpen}
        onOpenChange={setSyncDialogOpen}
        onConfirm={handleConfirmSync}
        isLoading={syncAllPreviewMutation.isPending || syncPreview === null}
        isSyncing={syncAllConnectorsMutation.isPending}
        isSyncAll
        orphansByType={syncPreview?.orphans_by_type}
        orphansAvailableByType={syncPreview?.orphans_available_by_type}
        syncedCountByType={syncPreview?.synced_count_by_type}
      />
    </>
  );
}

export default function ProtectedSearchPage() {
  return (
    <ProtectedRoute>
      <SearchPage />
    </ProtectedRoute>
  );
}
