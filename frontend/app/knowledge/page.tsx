"use client";

import {
  type CheckboxSelectionCallbackParams,
  type ColDef,
  type GetRowIdParams,
  themeQuartz,
  type ValueFormatterParams,
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
import { KnowledgeSearchInput } from "@/components/knowledge-search-input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { StatusBadge, type Status } from "@/components/ui/status-badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  DeleteConfirmationDialog,
  formatFilesToDelete,
} from "../../components/delete-confirmation-dialog";
import GoogleDriveIcon from "../../components/icons/google-drive-logo";
import OneDriveIcon from "../../components/icons/one-drive-logo";
import SharePointIcon from "../../components/icons/share-point-logo";
import { useDeleteDocument } from "../api/mutations/useDeleteDocument";
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

interface IngestionStatus {
  status: Status;
  error?: string;
  data?: File;
}

function SearchPage() {
  const router = useRouter();
  const { files: taskFiles, refreshTasks } = useTask();
  const { parsedFilterData, queryOverride } = useKnowledgeFilter();
  const [selectedRows, setSelectedRows] = useState<File[]>([]);
  const [showBulkDeleteDialog, setShowBulkDeleteDialog] = useState(false);
  const lastErrorRef = useRef<string | null>(null);
  const [ingestionStatus, setIngestionStatus] = useState<IngestionStatus | null>(null);

  const deleteDocumentMutation = useDeleteDocument();
  const syncAllConnectorsMutation = useSyncAllConnectors();

  useEffect(() => {
    refreshTasks();
  }, [refreshTasks]);

  const { data: searchData = [], isFetching, error, isError } = useGetSearchQuery(
    queryOverride,
    parsedFilterData,
  );

  // Show toast notification for search errors
  useEffect(() => {
    if (isError && error) {
      const errorMessage = error instanceof Error ? error.message : "Search failed";
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
  // Convert TaskFiles to File format and merge with backend results
  const taskFilesAsFiles: File[] = taskFiles.map((taskFile) => {
    return {
      filename: taskFile.filename,
      mimetype: taskFile.mimetype,
      source_url: taskFile.source_url,
      size: taskFile.size,
      connector_type: taskFile.connector_type,
      status: taskFile.status,
      error: taskFile.error,
      embedding_model: taskFile.embedding_model,
      embedding_dimensions: taskFile.embedding_dimensions,
    };
  });
  // Create a map of task files by filename for quick lookup
  const taskFileMap = new Map(
    taskFilesAsFiles.map((file) => [file.filename, file]),
  );
  // Override backend files with task file status if they exist
  const backendFiles = (searchData as File[]).map((file) => {
    const taskFile = taskFileMap.get(file.filename);
    if (taskFile) {
      // Override backend file with task file data (includes status)
      return { ...file, ...taskFile };
    }
    return file;
  });

  const filteredTaskFiles = taskFilesAsFiles.filter((taskFile) => {
    return (
      taskFile.status !== "active" &&
      !backendFiles.some(
        (backendFile) => backendFile.filename === taskFile.filename,
      )
    );
  });
  // Combine task files first, then backend files
  const fileResults = [...backendFiles, ...filteredTaskFiles];
  const gridRef = useRef<AgGridReact>(null);

  const columnDefs: ColDef<File>[] = [
    {
      field: "filename",
      headerName: "Source",
      checkboxSelection: (params: CheckboxSelectionCallbackParams<File>) =>
        (params?.data?.status || "active") === "active",
      headerCheckboxSelection: true,
      initialFlex: 2,
      minWidth: 220,
      cellRenderer: ({ data, value }: CustomCellRendererProps<File>) => {
        // Read status directly from data on each render
        const status = data?.status || "active";
        const isActive = status === "active";
        return (
          <div className="flex items-center overflow-hidden w-full">
            <div
              className={`transition-opacity duration-200 ${
                isActive ? "w-0" : "w-7"
              }`}
            ></div>
            <button
              type="button"
              className="flex items-center gap-2 cursor-pointer hover:text-blue-600 transition-colors text-left flex-1 overflow-hidden"
              onClick={() => {
                if (!isActive) {
                  return;
                }
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
                  <span className="font-medium text-foreground truncate">
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
      valueFormatter: (params: ValueFormatterParams<File>) =>
        params.value ? `${Math.round(params.value / 1024)} KB` : "-",
    },
    {
      field: "mimetype",
      headerName: "Type",
    },
    {
      field: "owner",
      headerName: "Owner",
      valueFormatter: (params: ValueFormatterParams<File>) =>
        params.data?.owner_name || params.data?.owner_email || "—",
    },
    {
      field: "chunkCount",
      headerName: "Chunks",
      valueFormatter: (params: ValueFormatterParams<File>) =>
        params.data?.chunkCount?.toString() || "-",
    },
    {
      field: "avgScore",
      headerName: "Avg score",
      cellRenderer: ({ value }: CustomCellRendererProps<File>) => {
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
      width: 110,
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
      cellRenderer: ({ data }: CustomCellRendererProps<File>) => {
        const status = data?.status || "active";
        const error =
          typeof data?.error === "string" && data.error.trim().length > 0
            ? data.error.trim()
            : undefined;
        if (status === "failed" && error) {
          return (
            <button
              type="button"
              className="inline-flex items-center gap-1 text-red-500 transition hover:text-red-400"
              aria-label="View ingestion error"
              onClick={() => {setIngestionStatus({ status, error, data })}}
            >
              <StatusBadge
                status={status}
                className="pointer-events-none"
              />
            </button>
          );
        }
        return <StatusBadge status={status} />;
      },
    },
    {
      cellRenderer: ({ data }: CustomCellRendererProps<File>) => {
        const status = data?.status || "active";
        if (status !== "active") {
          return null;
        }
        return (
          <KnowledgeActionsDropdown
            filename={data?.filename || ""}
            connectorType={data?.connector_type}
          />
        );
      },
      cellStyle: {
        alignItems: "center",
        display: "flex",
        justifyContent: "center",
        padding: 0,
      },
      colId: "actions",
      filter: false,
      minWidth: 0,
      width: 40,
      resizable: false,
      sortable: false,
      initialFlex: 0,
    },
  ];

  const defaultColDef: ColDef<File> = {
    resizable: false,
    suppressMovable: true,
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

      await Promise.all(deletePromises);

      toast.success(
        `Successfully deleted ${selectedRows.length} document${
          selectedRows.length > 1 ? "s" : ""
        }`,
      );
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
          <h2 className="text-lg font-semibold">Project Knowledge</h2>
        </div>

        {/* Search Input Area */}
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
                  toast.info(result.message || "No cloud files to sync. Add files from cloud connectors first.");
                } else if (result.synced_connectors && result.synced_connectors.length > 0) {
                  toast.success(
                    `Sync started for ${result.synced_connectors.join(", ")}. Check task notifications for progress.`
                  );
                } else if (result.errors && result.errors.length > 0) {
                  toast.error("Some connectors failed to sync");
                }
              } catch (error) {
                toast.error(
                  error instanceof Error ? error.message : "Failed to sync connectors"
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
        <AgGridReact
          className="w-full overflow-auto"
          columnDefs={columnDefs as ColDef<File>[]}
          defaultColDef={defaultColDef}
          loading={isFetching}
          ref={gridRef}
          theme={themeQuartz.withParams({ browserColorScheme: "inherit" })}
          rowData={fileResults}
          rowSelection="multiple"
          rowMultiSelectWithClick={false}
          suppressRowClickSelection={true}
          getRowId={(params: GetRowIdParams<File>) => params.data?.filename}
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
      </div>

      {/* Status dialog */}
      {ingestionStatus && (
      <Dialog
        open={!!ingestionStatus}
        onOpenChange={(open) => !open && setIngestionStatus(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Ingestion failed</DialogTitle>
            <DialogDescription className="text-sm text-muted-foreground">
              {ingestionStatus.data?.filename || "Unknown file"}
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-md border border-destructive/20 bg-destructive/10 p-4 text-sm text-destructive">
            {ingestionStatus.error}
          </div>
        </DialogContent>
      </Dialog>)}

      {/* Bulk Delete Confirmation Dialog */}
      <DeleteConfirmationDialog
        open={showBulkDeleteDialog}
        onOpenChange={setShowBulkDeleteDialog}
        title={selectedRows.length > 1 ? "Delete Documents" : "Delete Document"}
        description={`Are you sure you want to delete ${
          selectedRows.length
        } document${
          selectedRows.length > 1 ? "s" : ""
        }? This will remove all chunks and data associated with these documents. This action cannot be undone.

Documents to be deleted:
${formatFilesToDelete(selectedRows)}`}
        confirmText={selectedRows.length > 1 ? "Delete All" : "Delete"}
        onConfirm={handleBulkDelete}
        isLoading={deleteDocumentMutation.isPending}
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
