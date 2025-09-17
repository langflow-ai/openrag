"use client";

import {
  Building2,
  Cloud,
  FileText,
  HardDrive,
  Loader2,
  Search,
} from "lucide-react";
import { AgGridReact, CustomCellRendererProps } from "ag-grid-react";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useState,
  useRef,
} from "react";
import { SiGoogledrive } from "react-icons/si";
import { TbBrandOnedrive } from "react-icons/tb";
import { KnowledgeDropdown } from "@/components/knowledge-dropdown";
import { ProtectedRoute } from "@/components/protected-route";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useTask } from "@/contexts/task-context";
import { type File, useGetSearchQuery } from "../api/queries/useGetSearchQuery";
import { ColDef, RowClickedEvent } from "ag-grid-community";
import "@/components/AgGrid/registerAgGridModules";
import "@/components/AgGrid/agGridStyles.css";
import { KnowledgeActionsDropdown } from "@/components/knowledge-actions-dropdown";

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
  const { isMenuOpen } = useTask();
  const { parsedFilterData, isPanelOpen } = useKnowledgeFilter();
  const [query, setQuery] = useState("");
  const [queryInputText, setQueryInputText] = useState("");
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

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
      cellRenderer: ({ data, value }: CustomCellRendererProps<File>) => {
        return (
          <div className="flex items-center gap-2">
            {getSourceIcon(data?.connector_type)}
            <span className="font-medium text-foreground truncate">
              {value}
            </span>
          </div>
        );
      },
    },
    {
      field: "size",
      headerName: "Size",
      valueFormatter: params =>
        params.value ? `${Math.round(params.value / 1024)} KB` : "-",
    },
    {
      field: "mimetype",
      headerName: "Type",
    },
    {
      field: "owner",
      headerName: "Owner",
      valueFormatter: params =>
        params.value ||
        params.data?.owner_name ||
        params.data?.owner_email ||
        "—",
    },

    {
      field: "chunkCount",
      headerName: "Chunks",
    },
    {
      field: "avgScore",
      headerName: "Avg score",
      cellRenderer: ({ value }: CustomCellRendererProps<File>) => {
        return (
          <span className="text-xs text-green-400 bg-green-400/20 px-2 py-1 rounded">
            {value.toFixed(2)}
          </span>
        );
      },
    },
    {
      cellRenderer: () => {
        return <KnowledgeActionsDropdown />;
      },
      cellStyle: {
        alignItems: "center",
        display: "flex",
        justifyContent: "center",
        padding: 0,
      },
      colId: "actions",
      filter: false,
      maxWidth: 60,
      minWidth: 60,
      resizable: false,
      sortable: false,
      initialFlex: 0,
    },
  ]);

  const defaultColDef: ColDef<File> = {
    cellStyle: () => ({
      display: "flex",
      alignItems: "center",
    }),
    initialFlex: 1,
    minWidth: 100,
    resizable: false,
    suppressMovable: true,
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
              className="flex-1 bg-muted/20 rounded-lg border border-border/50 px-4 py-3 h-12 focus-visible:ring-1 focus-visible:ring-ring"
            />
            <Button
              type="submit"
              variant="outline"
              className="rounded-lg h-12 w-12 p-0 flex-shrink-0"
            >
              {isFetching ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
            </Button>
          </form>
        </div>
        {selectedFile ? (
          // Show chunks for selected file
          <>
            <div className="flex items-center gap-2 mb-4">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSelectedFile(null)}
              >
                ← Back to files
              </Button>
              <span className="text-sm text-muted-foreground">
                Chunks from {selectedFile}
              </span>
            </div>
            {fileResults
              .filter(file => file.filename === selectedFile)
              .flatMap(file => file.chunks)
              .map((chunk, index) => (
                <div
                  key={chunk.filename + index}
                  className="bg-muted/20 rounded-lg p-4 border border-border/50"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-blue-400" />
                      <span className="font-medium truncate">
                        {chunk.filename}
                      </span>
                    </div>
                    <span className="text-xs text-green-400 bg-green-400/20 px-2 py-1 rounded">
                      {chunk.score.toFixed(2)}
                    </span>
                  </div>
                  <div className="text-sm text-muted-foreground mb-2">
                    {chunk.mimetype} • Page {chunk.page}
                  </div>
                  <p className="text-sm text-foreground/90 leading-relaxed">
                    {chunk.text}
                  </p>
                </div>
              ))}
          </>
        ) : (
          <AgGridReact
            columnDefs={columnDefs}
            defaultColDef={defaultColDef}
            loading={isFetching}
            ref={gridRef}
            rowData={fileResults}
            onRowClicked={(params: RowClickedEvent<File>) => {
              setSelectedFile(params.data?.filename ?? "");
            }}
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
        )}
      </div>
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
