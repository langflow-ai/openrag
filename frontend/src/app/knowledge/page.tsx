"use client";

import {
  themeQuartz,
  type ColDef,
  type GetRowIdParams,
} from "ag-grid-community";
import { AgGridReact, type CustomCellRendererProps } from "ag-grid-react";
import { Cloud, FileIcon, Globe } from "lucide-react";
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
import { StatusBadge } from "@/components/ui/status-badge";
import { DeleteConfirmationDialog } from "../../../components/confirmation-dialog";
import { useDeleteDocument } from "../api/mutations/useDeleteDocument";
import GoogleDriveIcon from "../settings/icons/google-drive-icon";
import OneDriveIcon from "../settings/icons/one-drive-icon";
import SharePointIcon from "../settings/icons/share-point-icon";
import { KnowledgeSearchInput } from "@/components/knowledge-search-input";

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

function SearchPage() {
  const router = useRouter();
  const { files: taskFiles, refreshTasks } = useTask();
  const { parsedFilterData, queryOverride } = useKnowledgeFilter();
  const [selectedRows, setSelectedRows] = useState<File[]>([]);
  const [showBulkDeleteDialog, setShowBulkDeleteDialog] = useState(false);

  const deleteDocumentMutation = useDeleteDocument();

  useEffect(() => {
    refreshTasks();
  }, [refreshTasks]);

  const { data: searchData = [], isFetching } = useGetSearchQuery(
    queryOverride,
    parsedFilterData
  );
  // Convert TaskFiles to File format and merge with backend results
  const taskFilesAsFiles: File[] = taskFiles.map((taskFile) => {
    return {
      filename: taskFile.filename,
      mimetype: taskFile.mimetype,
      source_url: taskFile.source_url,
      size: taskFile.size,
      connector_type: taskFile.connector_type,
      status: taskFile.status,
    };
  });

  // Create a map of task files by filename for quick lookup
  const taskFileMap = new Map(
    taskFilesAsFiles.map((file) => [file.filename, file])
  );

  // Override backend files with task file status if they exist
  const backendFiles = (searchData as File[])
    .map((file) => {
      const taskFile = taskFileMap.get(file.filename);
      if (taskFile) {
        // Override backend file with task file data (includes status)
        return { ...file, ...taskFile };
      }
      return file;
    })
    .filter((file) => {
      // Only filter out files that are currently processing AND in taskFiles
      const taskFile = taskFileMap.get(file.filename);
      return !taskFile || taskFile.status !== "processing";
    });

  const filteredTaskFiles = taskFilesAsFiles.filter((taskFile) => {
    return (
      taskFile.status !== "active" &&
      !backendFiles.some(
        (backendFile) => backendFile.filename === taskFile.filename
      )
    );
  });

  // Combine task files first, then backend files
  const fileResults = [...backendFiles, ...filteredTaskFiles];

  const gridRef = useRef<AgGridReact>(null);

  const columnDefs = [
    {
      field: "filename",
      headerName: "Source",
      checkboxSelection: (params: CustomCellRendererProps<File>) =>
        (params?.data?.status || "active") === "active",
      headerCheckboxSelection: true,
      initialFlex: 2,
      minWidth: 220,
      cellRenderer: ({ data, value }: CustomCellRendererProps<File>) => {
        // Read status directly from data on each render
        const status = data?.status || "active";
        const isActive = status === "active";
        console.log(data?.filename, status, "a");
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
                    data?.filename ?? ""
                  )}`
                );
              }}
            >
              {getSourceIcon(data?.connector_type)}
              <span className="font-medium text-foreground truncate">
                {value}
              </span>
            </button>
          </div>
        );
      },
    },
    {
      field: "size",
      headerName: "Size",
      valueFormatter: (params: CustomCellRendererProps<File>) =>
        params.value ? `${Math.round(params.value / 1024)} KB` : "-",
    },
    {
      field: "mimetype",
      headerName: "Type",
    },
    {
      field: "owner",
      headerName: "Owner",
      valueFormatter: (params: CustomCellRendererProps<File>) =>
        params.data?.owner_name || params.data?.owner_email || "—",
    },
    {
      field: "chunkCount",
      headerName: "Chunks",
      valueFormatter: (params: CustomCellRendererProps<File>) =>
        params.data?.chunkCount?.toString() || "-",
    },
    {
      field: "avgScore",
      headerName: "Avg score",
      initialFlex: 0.5,
      cellRenderer: ({ value }: CustomCellRendererProps<File>) => {
        return (
          <span className="text-xs text-accent-emerald-foreground bg-accent-emerald px-2 py-1 rounded">
            {value?.toFixed(2) ?? "-"}
          </span>
        );
      },
    },
    {
      field: "status",
      headerName: "Status",
      cellRenderer: ({ data }: CustomCellRendererProps<File>) => {
        console.log(data?.filename, data?.status, "b");
        // Default to 'active' status if no status is provided
        const status = data?.status || "active";
        return <StatusBadge status={status} />;
      },
    },
    {
      cellRenderer: ({ data }: CustomCellRendererProps<File>) => {
        const status = data?.status || "active";
        if (status !== "active") {
          return null;
        }
        return <KnowledgeActionsDropdown filename={data?.filename || ""} />;
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
        deleteDocumentMutation.mutateAsync({ filename: row.filename })
      );

      await Promise.all(deletePromises);

      toast.success(
        `Successfully deleted ${selectedRows.length} document${
          selectedRows.length > 1 ? "s" : ""
        }`
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
          : "Failed to delete some documents"
      );
    }
  };

  return (
    <>
      <div className="flex flex-col h-full">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold">Project Knowledge</h2>
        </div>

        {/* Search Input Area */}
        <div className="flex-1 flex items-center flex-shrink-0 flex-wrap-reverse gap-3 mb-6">
          <KnowledgeSearchInput />
          {/* //TODO: Implement sync button */}
          {/* <Button
              type="button"
              variant="outline"
              className="rounded-lg flex-shrink-0"
              onClick={() => alert("Not implemented")}
            >
              Sync
            </Button> */}
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

      {/* Bulk Delete Confirmation Dialog */}
      <DeleteConfirmationDialog
        open={showBulkDeleteDialog}
        onOpenChange={setShowBulkDeleteDialog}
        title="Delete Documents"
        description={`Are you sure you want to delete ${
          selectedRows.length
        } document${
          selectedRows.length > 1 ? "s" : ""
        }? This will remove all chunks and data associated with these documents. This action cannot be undone.

Documents to be deleted:
${selectedRows.map((row) => `• ${row.filename}`).join("\n")}`}
        confirmText="Delete All"
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
