"use client";

import {
  Building2,
  Cloud,
  HardDrive,
  Loader2,
  Search,
  Trash2,
} from "lucide-react";
import { AgGridReact, CustomCellRendererProps } from "ag-grid-react";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useState,
  useRef,
} from "react";
import { useRouter } from "next/navigation";
import { SiGoogledrive } from "react-icons/si";
import { TbBrandOnedrive } from "react-icons/tb";
import { KnowledgeDropdown } from "@/components/knowledge-dropdown";
import { ProtectedRoute } from "@/components/protected-route";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useTask } from "@/contexts/task-context";
import { type File, useGetSearchQuery } from "../api/queries/useGetSearchQuery";
import { ColDef } from "ag-grid-community";
import "@/components/AgGrid/registerAgGridModules";
import "@/components/AgGrid/agGridStyles.css";
import { KnowledgeActionsDropdown } from "@/components/knowledge-actions-dropdown";
import { DeleteConfirmationDialog } from "../../../components/confirmation-dialog";
import { useDeleteDocument } from "../api/mutations/useDeleteDocument";
import { toast } from "sonner";

// Function to get the appropriate icon for a connector type
function getSourceIcon(connectorType?: string) {
  switch (connectorType) {
    case "google_drive":
      return <SiGoogledrive className="h-4 w-4 text-foreground" />;
    case "onedrive":
      return <TbBrandOnedrive className="h-4 w-4 text-foreground" />;
    case "sharepoint":
      return <Building2 className="h-4 w-4 text-foreground" />;
    case "s3":
      return <Cloud className="h-4 w-4 text-foreground" />;
    default:
      return <HardDrive className="h-4 w-4 text-muted-foreground" />;
  }
}

function SearchPage() {
  const router = useRouter();
  const { isMenuOpen } = useTask();
  const { parsedFilterData, isPanelOpen } = useKnowledgeFilter();
  const [query, setQuery] = useState("");
  const [queryInputText, setQueryInputText] = useState("");
  const [selectedRows, setSelectedRows] = useState<File[]>([]);
  const [showBulkDeleteDialog, setShowBulkDeleteDialog] = useState(false);

  const deleteDocumentMutation = useDeleteDocument();

  const {
    data = [],
    isFetching,
    refetch: refetchSearch,
  } = useGetSearchQuery(query, parsedFilterData);

  // Update query when global filter changes
  useEffect(() => {
    if (parsedFilterData?.query) {
      setQueryInputText(parsedFilterData.query);
    }
  }, [parsedFilterData]);

  const handleSearch = useCallback(
    (e?: FormEvent<HTMLFormElement>) => {
      if (e) e.preventDefault();
      if (query.trim() === queryInputText.trim()) {
        refetchSearch();
        return;
      }
      setQuery(queryInputText);
    },
    [queryInputText, refetchSearch, query]
  );

  const fileResults = data as File[];

  const gridRef = useRef<AgGridReact>(null);

  const [columnDefs] = useState<ColDef<File>[]>([
    {
      field: "filename",
      headerName: "Source",
      checkboxSelection: true,
      headerCheckboxSelection: true,
      flex: 3,
      minWidth: 200,
      cellRenderer: ({ data, value }: CustomCellRendererProps<File>) => {
        return (
          <div className="flex items-center gap-2 ml-2 w-full">
            <div
              className="flex items-center gap-2 cursor-pointer hover:text-blue-600 transition-colors"
              onClick={e => {
                e.preventDefault();
                e.stopPropagation();
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
            </div>
          </div>
        );
      },
      cellStyle: {
        display: "flex",
        alignItems: "center",
      },
    },
    {
      field: "size",
      headerName: "Size",
      flex: 2,
      minWidth: 80,
      valueFormatter: params =>
        params.value ? `${Math.round(params.value / 1024)} KB` : "-",
    },
    {
      field: "mimetype",
      headerName: "Type",
      flex: 2,
      minWidth: 80,
    },
    {
      field: "owner",
      headerName: "Owner",
      flex: 2,
      minWidth: 120,
      valueFormatter: params =>
        params.data?.owner_name || params.data?.owner_email || "—",
    },

    {
      field: "chunkCount",
      headerName: "Chunks",
      flex: 2,
      minWidth: 70,
    },
    {
      field: "avgScore",
      headerName: "Avg score",
      flex: 2,
      minWidth: 90,
      cellRenderer: ({ value }: CustomCellRendererProps<File>) => {
        return (
          <span className="text-xs text-green-400 bg-green-400/20 px-2 py-1 rounded">
            {value.toFixed(2)}
          </span>
        );
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
      width: 60,
      minWidth: 60,
      maxWidth: 60,
      resizable: false,
      sortable: false,
      flex: 0,
    },
  ]);

  const defaultColDef: ColDef<File> = {
    cellStyle: () => ({
      display: "flex",
      alignItems: "center",
    }),
    resizable: false,
    suppressMovable: true,
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
      const deletePromises = selectedRows.map(row =>
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
    <div
      className={`fixed inset-0 md:left-72 top-[53px] flex flex-col transition-all duration-300 ${
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
    >
      <div className="flex-1 flex flex-col min-h-0 px-6 py-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold">Project Knowledge</h2>
          <KnowledgeDropdown variant="button" />
        </div>

        {/* Search Input Area */}
        <div className="flex-shrink-0 mb-6 lg:max-w-[75%] xl:max-w-[50%]">
          <form onSubmit={handleSearch} className="flex gap-3">
            <Input
              name="search-query"
              id="search-query"
              type="text"
              defaultValue={parsedFilterData?.query}
              value={queryInputText}
              onChange={e => setQueryInputText(e.target.value)}
              placeholder="Search your documents..."
              className="flex-1 bg-muted/20 rounded-lg border border-border/50 px-4 py-3 focus-visible:ring-1 focus-visible:ring-ring"
            />
            <Button
              type="submit"
              variant="outline"
              className="rounded-lg p-0 flex-shrink-0"
            >
              {isFetching ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
            </Button>
            {/* //TODO: Implement sync button */}
            {/* <Button
              type="button"
              variant="outline"
              className="rounded-lg flex-shrink-0"
              onClick={() => alert("Not implemented")}
            >
              Sync
            </Button> */}
            <Button
              type="button"
              variant="destructive"
              className="rounded-lg flex-shrink-0"
              onClick={() => setShowBulkDeleteDialog(true)}
              disabled={selectedRows.length === 0}
            >
              <Trash2 className="h-4 w-4" /> Delete
            </Button>
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
          getRowId={params => params.data.filename}
          onSelectionChanged={onSelectionChanged}
          suppressHorizontalScroll={false}
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
${selectedRows.map(row => `• ${row.filename}`).join("\n")}`}
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
