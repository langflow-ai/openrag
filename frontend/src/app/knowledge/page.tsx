"use client";

import { themeQuartz, type ColDef } from "ag-grid-community";
import { AgGridReact, type CustomCellRendererProps } from "ag-grid-react";
import { ArrowRight, Cloud, FileIcon, Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  type ChangeEvent,
  FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
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
import { filterAccentClasses } from "@/components/knowledge-filter-panel";
import GoogleDriveIcon from "../settings/icons/google-drive-icon";
import OneDriveIcon from "../settings/icons/one-drive-icon";
import SharePointIcon from "../settings/icons/share-point-icon";
import { cn } from "@/lib/utils";

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
  const { files: taskFiles } = useTask();
  const {
    selectedFilter,
    setSelectedFilter,
    parsedFilterData,
    queryOverride,
    setQueryOverride,
  } = useKnowledgeFilter();
  const [searchQueryInput, setSearchQueryInput] = useState(queryOverride || "");
  const [selectedRows, setSelectedRows] = useState<File[]>([]);
  const [showBulkDeleteDialog, setShowBulkDeleteDialog] = useState(false);

  const deleteDocumentMutation = useDeleteDocument();

  const { data = [], isFetching } = useGetSearchQuery(
    queryOverride,
    parsedFilterData
  );

  const handleSearch = useCallback(
    (e?: FormEvent<HTMLFormElement>) => {
      if (e) e.preventDefault();
      setQueryOverride(searchQueryInput.trim());
    },
    [searchQueryInput, setQueryOverride]
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

  const backendFiles = data as File[];

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

  const [columnDefs] = useState<ColDef<File>[]>([
    {
      field: "filename",
      headerName: "Source",
      checkboxSelection: true,
      headerCheckboxSelection: true,
      initialFlex: 2,
      minWidth: 220,
      cellRenderer: ({ data, value }: CustomCellRendererProps<File>) => {
        return (
          <button
            type="button"
            className="flex items-center gap-2 cursor-pointer hover:text-blue-600 transition-colors text-left w-full"
            onClick={() => {
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
        );
      },
    },
    {
      field: "size",
      headerName: "Size",
      valueFormatter: (params) =>
        params.value ? `${Math.round(params.value / 1024)} KB` : "-",
    },
    {
      field: "mimetype",
      headerName: "Type",
    },
    {
      field: "owner",
      headerName: "Owner",
      valueFormatter: (params) =>
        params.data?.owner_name || params.data?.owner_email || "—",
    },
    {
      field: "chunkCount",
      headerName: "Chunks",
      valueFormatter: (params) => params.data?.chunkCount?.toString() || "-",
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
      field: "status",
      headerName: "Status",
      cellRenderer: ({ data }: CustomCellRendererProps<File>) => {
        // Default to 'active' status if no status is provided
        const status = data?.status || "active";
        return <StatusBadge status={status} />;
      },
    },
    {
      cellRenderer: ({ data }: CustomCellRendererProps<File>) => {
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
  ]);

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

  // Reset the query text when the selected filter changes
  useEffect(() => {
    setSearchQueryInput(queryOverride);
  }, [queryOverride]);

  return (
    <>
      <div className="flex flex-col h-full">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold">Knowledge</h2>
        </div>

        {/* Search Input Area */}
        <div className="flex-1 flex flex-shrink-0 flex-wrap-reverse gap-3 mb-6">
          <form
            className="flex flex-1 gap-3 max-w-full"
            onSubmit={handleSearch}
          >
            <div className="primary-input group/input min-h-10 !flex items-center flex-nowrap focus-within:border-foreground transition-colors !p-[0.3rem] max-w-[min(640px,100%)] min-w-[100px]">
              {selectedFilter?.name && (
                <div
                  title={selectedFilter?.name}
                  className={`flex items-center gap-1 h-full px-1.5 py-0.5 mr-1 rounded max-w-[25%] ${
                    filterAccentClasses[parsedFilterData?.color || "zinc"]
                  }`}
                >
                  <span className="truncate">{selectedFilter?.name}</span>
                  <X
                    aria-label="Remove filter"
                    className="h-4 w-4 flex-shrink-0 cursor-pointer"
                    onClick={() => setSelectedFilter(null)}
                  />
                </div>
              )}
              <Search
                className="h-4 w-4 ml-1 flex-shrink-0 text-placeholder-foreground"
                strokeWidth={1.5}
              />
              <input
                className="bg-transparent w-full h-full ml-2 focus:outline-none focus-visible:outline-none font-mono placeholder:font-mono"
                name="search-query"
                id="search-query"
                type="text"
                placeholder="Search your documents..."
                value={searchQueryInput}
                onChange={(e: ChangeEvent<HTMLInputElement>) =>
                  setSearchQueryInput(e.target.value)
                }
              />
              {queryOverride && (
                <Button
                  variant="ghost"
                  className="h-full !px-1.5 !py-0"
                  type="button"
                  onClick={() => {
                    setSearchQueryInput("");
                    setQueryOverride("");
                  }}
                >
                  <X className="h-4 w-4" />
                </Button>
              )}
              <Button
                variant="ghost"
                className={cn(
                  "h-full !px-1.5 !py-0 hidden group-focus-within/input:block",
                  searchQueryInput && "block"
                )}
                type="submit"
              >
                <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
            {/* <Button
              type="submit"
              variant="outline"
              className="rounded-lg p-0 flex-shrink-0"
            >
              {isFetching ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
            </Button> */}
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
          </form>
          <div className="ml-auto">
            <KnowledgeDropdown />
          </div>
        </div>
        <AgGridReact
          className="w-full overflow-auto"
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          loading={isFetching}
          ref={gridRef}
          rowData={fileResults}
          rowSelection="multiple"
          rowMultiSelectWithClick={false}
          suppressRowClickSelection={true}
          getRowId={(params) => params.data.filename}
          domLayout="normal"
          theme={themeQuartz.withParams({ browserColorScheme: "inherit" })}
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
        }? This will remove all chunks and data associated with these documents. This action cannot be undone.`}
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
