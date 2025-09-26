"use client";

import type { ColDef } from "ag-grid-community";
import { AgGridReact, type CustomCellRendererProps } from "ag-grid-react";
import { Building2, Cloud, HardDrive, Search, Trash2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { type ChangeEvent, useCallback, useRef, useState } from "react";
import { SiGoogledrive } from "react-icons/si";
import { TbBrandOnedrive } from "react-icons/tb";
import { KnowledgeDropdown } from "@/components/knowledge-dropdown";
import { ProtectedRoute } from "@/components/protected-route";
import { Button } from "@/components/ui/button";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useLayout } from "@/contexts/layout-context";
import { useTask } from "@/contexts/task-context";
import { type File, useGetSearchQuery } from "../api/queries/useGetSearchQuery";
import "@/components/AgGrid/registerAgGridModules";
import "@/components/AgGrid/agGridStyles.css";
import { toast } from "sonner";
import { KnowledgeActionsDropdown } from "@/components/knowledge-actions-dropdown";
import { StatusBadge } from "@/components/ui/status-badge";
import { DeleteConfirmationDialog } from "../../../components/confirmation-dialog";
import { useDeleteDocument } from "../api/mutations/useDeleteDocument";

// Function to get the appropriate icon for a connector type
function getSourceIcon(connectorType?: string) {
  switch (connectorType) {
    case "google_drive":
      return (
        <SiGoogledrive className="h-4 w-4 text-foreground flex-shrink-0" />
      );
    case "onedrive":
      return (
        <TbBrandOnedrive className="h-4 w-4 text-foreground flex-shrink-0" />
      );
    case "sharepoint":
      return <Building2 className="h-4 w-4 text-foreground flex-shrink-0" />;
    case "s3":
      return <Cloud className="h-4 w-4 text-foreground flex-shrink-0" />;
    default:
      return (
        <HardDrive className="h-4 w-4 text-muted-foreground flex-shrink-0" />
      );
  }
}

function SearchPage() {
  const router = useRouter();
  const { isMenuOpen, files: taskFiles } = useTask();
  const { totalTopOffset } = useLayout();
  const { selectedFilter, setSelectedFilter, parsedFilterData, isPanelOpen } =
    useKnowledgeFilter();
  const [selectedRows, setSelectedRows] = useState<File[]>([]);
  const [showBulkDeleteDialog, setShowBulkDeleteDialog] = useState(false);

  const deleteDocumentMutation = useDeleteDocument();

  const { data = [], isFetching } = useGetSearchQuery(
    parsedFilterData?.query || "*",
    parsedFilterData,
  );

  const handleTableSearch = (e: ChangeEvent<HTMLInputElement>) => {
    gridRef.current?.api.setGridOption("quickFilterText", e.target.value);
  };

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
        (backendFile) => backendFile.filename === taskFile.filename,
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
                  data?.filename ?? "",
                )}`,
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
      initialFlex: 0.5,
      cellRenderer: ({ value }: CustomCellRendererProps<File>) => {
        return (
          <span className="text-xs text-green-400 bg-green-400/20 px-2 py-1 rounded">
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

  return (
    <div
      className={`fixed inset-0 md:left-72 flex flex-col transition-all duration-300 ${
        isMenuOpen && isPanelOpen
          ? "md:right-[704px]"
          : // Both open: 384px (menu) + 320px (KF panel)
          isMenuOpen
          ? "md:right-96"
          : // Only menu open: 384px
          isPanelOpen
          ? "md:right-80"
          : // Only KF panel open: 320px
            "md:right-6" // Neither open: 24px
      }`}
      style={{ top: `${totalTopOffset}px` }}
    >
      <div className="flex-1 flex flex-col min-h-0 px-6 py-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold">Project Knowledge</h2>
          <KnowledgeDropdown variant="button" />
        </div>

        {/* Search Input Area */}
        <div className="flex-shrink-0 mb-6 xl:max-w-[75%]">
          <form className="flex gap-3">
            <div className="primary-input min-h-10 !flex items-center flex-nowrap gap-2 focus-within:border-foreground transition-colors !py-0">
              {selectedFilter?.name && (
                <div className="flex items-center gap-1 bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded max-w-[300px]">
                  <span className="truncate">{selectedFilter?.name}</span>
                  <X
                    aria-label="Remove filter"
                    className="h-4 w-4 flex-shrink-0 cursor-pointer"
                    onClick={() => setSelectedFilter(null)}
                  />
                </div>
              )}
              <input
                className="bg-transparent w-full h-full focus:outline-none focus-visible:outline-none placeholder:font-mono"
                name="search-query"
                id="search-query"
                type="text"
                placeholder="Search your documents..."
                onChange={handleTableSearch}
              />
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
                <Trash2 className="h-4 w-4" /> Delete
              </Button>
            )}
          </form>
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
          domLayout="autoHeight"
          onSelectionChanged={onSelectionChanged}
          noRowsOverlayComponent={() => (
            <div className="text-center">
              <Search className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
              <p className="text-lg text-muted-foreground">
                No documents found
              </p>
              <p className="text-sm text-muted-foreground/70 mt-2">
                Try adjusting your search terms
              </p>
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
    </div>
  );
}

export default function ProtectedSearchPage() {
  return (
    <ProtectedRoute>
      <SearchPage />
    </ProtectedRoute>
  );
}
