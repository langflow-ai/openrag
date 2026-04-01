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
import { Cloud, FileIcon, Globe, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { KnowledgeDropdown } from "@/components/knowledge-dropdown";
import { ProtectedRoute } from "@/components/protected-route";
import { Button } from "@/components/ui/button";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useTask } from "@/contexts/task-context";
import { type File, useGetSearchQuery } from "../api/queries/useGetSearchQuery";
import "@/components/AgGrid/registerAgGridModules";
import "@/components/AgGrid/agGridStyles.css";
import { toast } from "sonner";
import { KnowledgeActionsDropdown } from "@/components/knowledge-actions-dropdown";
import { KnowledgeSearchBar } from "@/components/knowledge-search-bar";
import { KnowledgeSearchInput } from "@/components/knowledge-search-input";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useIsCloudBrand } from "@/contexts/brand-context";
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
import AwsLogo from "../../components/icons/aws-logo";
import GoogleDriveIcon from "../../components/icons/google-drive-logo";
import IBMCOSIcon from "../../components/icons/ibm-cos-icon";
import IBMLogo from "../../components/icons/ibm-logo";
import OneDriveIcon from "../../components/icons/one-drive-logo";
import SharePointIcon from "../../components/icons/share-point-logo";
import { useDeleteDocument } from "../api/mutations/useDeleteDocument";
import { useRefreshOpenragDocs } from "../api/mutations/useRefreshOpenragDocs";
import { useSyncAllConnectors } from "../api/mutations/useSyncConnector";

// Function to get the appropriate icon for a connector type
function getSourceIcon(connectorType?: string) {
  switch (connectorType) {
    case "google_drive":
      return (
        <GoogleDriveIcon className="h-4 w-4 text-foreground flex-shrink-0" />
      );
    case "onedrive":
      return <OneDriveIcon className="h-4 w-4 text-foreground flex-shrink-0" />;
    case "sharepoint":
      return (
        <SharePointIcon className="h-4 w-4 text-foreground flex-shrink-0" />
      );
    case "openrag_docs":
    case "url":
      return <Globe className="h-4 w-4 text-muted-foreground flex-shrink-0" />;
    case "s3":
      return <Cloud className="h-4 w-4 text-foreground flex-shrink-0" />;
    case "ibm_cos":
      return <IBMCOSIcon className="h-4 w-4 flex-shrink-0" />;
    case "aws_s3":
      return <AwsLogo className="h-4 w-4 flex-shrink-0" />;
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
  const { parsedFilterData, queryOverride } = useKnowledgeFilter();
  const [selectedRows, setSelectedRows] = useState<File[]>([]);
  const [showBulkDeleteDialog, setShowBulkDeleteDialog] = useState(false);
  const lastErrorRef = useRef<string | null>(null);
  const hasInitializedFailedFilesRef = useRef(false);
  const seenFailedFileKeysRef = useRef<Set<string>>(new Set());

  const deleteDocumentMutation = useDeleteDocument();
  const syncAllConnectorsMutation = useSyncAllConnectors();
  const refreshOpenragDocsMutation = useRefreshOpenragDocs();

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

  const {
    data: searchData = [],
    isLoading: isSearchLoading,
    error,
    isError,
  } = useGetSearchQuery(queryOverride, parsedFilterData, {
    refetchInterval: 5000,
  });

  const isOpenragDocsRow = useCallback((file?: File) => {
    return (
      file?.connector_type === "openrag_docs" ||
      file?.connector_type === "system_default"
    );
  }, []);

  const getFileIdentity = useCallback((file?: File) => {
    return getKnowledgeFileIdentity(file);
  }, []);

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
  const fileResults = buildKnowledgeTableRows(
    searchData as File[],
    taskFiles,
    !!parsedFilterData,
  );

  const gridRows = fileResults;
  const gridRef = useRef<AgGridReact>(null);

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
        (params?.data?.status || "active") === "active",
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
    if (gridRef.current) {
      const selectedNodes = gridRef.current.api.getSelectedRows();
      setSelectedRows(selectedNodes);
    }
  }, []);

  const handleBulkDelete = async () => {
    if (selectedRows.length === 0) return;

    try {
      // Delete each file individually since the API expects one filename at a time
      const deletePromises = selectedRows.map((row) =>
        deleteDocumentMutation.mutateAsync({ filename: row.filename }),
      );

      const deleteResults = await Promise.all(deletePromises);
      await refreshTasks();
      await queryClient.invalidateQueries({ queryKey: ["search"] });
      await queryClient.refetchQueries({ queryKey: ["search"] });

      const totalDeletedChunks = deleteResults.reduce(
        (sum, result) => sum + (result.deleted_chunks || 0),
        0,
      );
      const filesWithNoDeletion = deleteResults.filter(
        (result) => (result.deleted_chunks || 0) === 0,
      );

      if (totalDeletedChunks > 0) {
        toast.success(
          `Successfully deleted ${selectedRows.length} document${
            selectedRows.length > 1 ? "s" : ""
          }`,
        );
      } else {
        toast.warning(
          "No document chunks were deleted. Files may be owned by another context or already removed.",
        );
      }

      if (filesWithNoDeletion.length > 0 && totalDeletedChunks > 0) {
        toast.warning(
          `${filesWithNoDeletion.length} selected file${
            filesWithNoDeletion.length > 1 ? "s were" : " was"
          } not deleted (0 chunks matched).`,
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
          <KnowledgeSearchBar />
        ) : (
          /* Search Input Area */
          <div className="flex-1 flex items-center flex-shrink-0 flex-wrap-reverse gap-3 mb-6">
            <KnowledgeSearchInput />

            <Button
              type="button"
              variant="outline"
              className="rounded-lg flex-shrink-0"
              disabled={syncAllConnectorsMutation.isPending}
              onClick={async () => {
                try {
                  toast.info("Syncing all cloud connectors...");
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
                    error instanceof Error
                      ? error.message
                      : "Failed to sync connectors",
                  );
                }
              }}
            >
              {syncAllConnectorsMutation.isPending ? (
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
        {isCloudBrand ? (
          <AgGridReact
            className="w-full overflow-auto border"
            columnDefs={columnDefs as ColDef<File>[]}
            defaultColDef={defaultColDef}
            loading={isSearchLoading || deleteDocumentMutation.isPending}
            ref={gridRef}
            theme={themeQuartz.withParams({ browserColorScheme: "inherit" })}
            rowData={gridRows}
            rowSelection="multiple"
            getRowId={(params: GetRowIdParams<File>) =>
              getFileIdentity(params.data)
            }
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
            loading={isSearchLoading || deleteDocumentMutation.isPending}
            ref={gridRef}
            theme={themeQuartz.withParams({ browserColorScheme: "inherit" })}
            rowData={gridRows}
            rowSelection="multiple"
            rowMultiSelectWithClick={false}
            suppressRowClickSelection={true}
            getRowId={(params: GetRowIdParams<File>) =>
              getFileIdentity(params.data)
            }
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
