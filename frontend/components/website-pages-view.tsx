"use client";

import { type ColDef, type ColumnState } from "ag-grid-community";
import { AgGridReact, type CustomCellRendererProps } from "ag-grid-react";
import { MoreVertical, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  EMPTY_SEARCH_RESULT,
  type File,
  type SearchResult,
  useGetSearchQuery,
} from "@/app/api/queries/useGetSearchQuery";
import { KnowledgeDataTable } from "@/components/knowledge-data-table";
import { KnowledgePaginationFooter } from "@/components/knowledge-pagination-footer";
import { KnowledgeSearchBar } from "@/components/knowledge-search-bar";
import { KnowledgeUrlIcon } from "@/components/knowledge-url-icon";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { StatusBadge } from "@/components/ui/status-badge";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { SEARCH_CONSTANTS } from "@/lib/constants";
import { formatFileSize } from "@/lib/file-format";
import { cn } from "@/lib/utils";

type Source = {
  id: string;
  name: string;
  starting_url: string;
  status: "active" | "processing" | "failed";
  web_child_count?: number;
  last_successful_sync_at?: string | null;
};

const lastSyncFormatter = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function formatLastSync(value?: string | null) {
  if (!value) return "Last synced —";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Last synced —";
  return `Last synced ${lastSyncFormatter.format(date)}`;
}

export function WebsitePagesView({ sourceId }: { sourceId: string }) {
  const router = useRouter();
  const isCloudBrand = useIsCloudBrand();
  const gridRef = useRef<AgGridReact<File>>(null);
  const cursorCacheRef = useRef<Map<number, Record<string, unknown>>>(
    new Map(),
  );
  const [source, setSource] = useState<Source | null>(null);
  const [sourceLoading, setSourceLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [currentPageSize, setCurrentPageSize] = useState(25);
  const [sortBy, setSortBy] = useState("filename");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [isSyncing, setIsSyncing] = useState(false);

  const websiteSearchQuery = useMemo(
    () => ({
      query: "",
      filters: {
        data_sources: [],
        document_types: [],
        owners: [],
        connector_types: [],
        web_source_ids: [sourceId],
      },
      limit: SEARCH_CONSTANTS.WILDCARD_QUERY_LIMIT,
      scoreThreshold: 0,
      color: "zinc" as const,
      icon: "folder" as const,
    }),
    [sourceId],
  );

  const loadSource = useCallback(async () => {
    setSourceLoading(true);
    try {
      const sourceResponse = await fetch(
        `/api/connectors/url/sources/${sourceId}`,
      );
      if (!sourceResponse.ok) {
        throw new Error("Website source was not found");
      }
      setSource(await sourceResponse.json());
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Could not load website pages",
      );
    } finally {
      setSourceLoading(false);
    }
  }, [sourceId]);

  useEffect(() => {
    void loadSource();
  }, [loadSource]);

  const {
    data: searchData = EMPTY_SEARCH_RESULT,
    isLoading: isPagesLoading,
    isFetching: isPagesFetching,
    refetch: refetchPages,
  } = useGetSearchQuery(
    search,
    websiteSearchQuery,
    { refetchInterval: 5000 },
    { groupBy: "document_id", resultMode: "website_pages" },
  );

  const { files: searchPages } = searchData as SearchResult;
  const sortedPages = useMemo(() => {
    const statusRank: Record<string, number> = {
      active: 0,
      processing: 1,
      sync: 2,
      failed: 3,
      unavailable: 4,
      disabled: 5,
    };
    const sortValue = (page: File): string | number => {
      switch (sortBy) {
        case "size":
          return page.size;
        case "chunkCount":
          return page.chunkCount ?? 0;
        case "status":
          return statusRank[page.status || "active"] ?? 99;
        case "source_url":
          return page.source_url;
        default:
          return page.filename;
      }
    };
    return [...searchPages].sort((left, right) => {
      const leftValue = sortValue(left);
      const rightValue = sortValue(right);
      const comparison =
        typeof leftValue === "number" && typeof rightValue === "number"
          ? leftValue - rightValue
          : String(leftValue).localeCompare(String(rightValue));
      return sortOrder === "desc" ? -comparison : comparison;
    });
  }, [searchPages, sortBy, sortOrder]);
  const total = sortedPages.length;
  const pages = sortedPages.slice(
    (currentPage - 1) * currentPageSize,
    currentPage * currentPageSize,
  );

  useEffect(() => {
    setCurrentPage(1);
  }, [search, currentPageSize, sortBy, sortOrder]);

  const action = useCallback(
    async (url: string, method = "POST") => {
      const response = await fetch(url, { method });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        toast.error(data.detail || data.error || "Action failed");
        return;
      }
      toast.success(method === "DELETE" ? "Page disabled" : "Sync started");
      void Promise.all([loadSource(), refetchPages()]);
    },
    [loadSource, refetchPages],
  );

  const syncSource = async () => {
    setIsSyncing(true);
    try {
      await action(`/api/connectors/url/sources/${sourceId}/sync`);
    } finally {
      setIsSyncing(false);
    }
  };

  const onSortChanged = useCallback(() => {
    const state: ColumnState | undefined = gridRef.current?.api
      .getColumnState()
      .find((column) => column.sort != null);
    setSortBy(state?.colId || "filename");
    setSortOrder(state?.sort === "desc" ? "desc" : "asc");
  }, []);

  const defaultColDef = useMemo<ColDef<File>>(
    () => ({
      resizable: false,
      suppressMovable: true,
      ...(isCloudBrand ? { sortable: false } : {}),
      initialFlex: 1,
      minWidth: 100,
    }),
    [isCloudBrand],
  );

  const columnDefs = useMemo<ColDef<File>[]>(
    () => [
      {
        field: "filename",
        headerName: "Title",
        sortable: true,
        checkboxSelection: true,
        headerCheckboxSelection: true,
        ...(isCloudBrand
          ? { flex: 2.2, minWidth: 260 }
          : { initialFlex: 2, minWidth: 220 }),
        cellRenderer: ({ data, value }: CustomCellRendererProps<File>) => (
          <div className="flex h-full w-full min-w-0 items-center overflow-hidden">
            <button
              type="button"
              className={cn(
                "flex flex-1 items-center gap-2 overflow-hidden text-left transition-colors",
                isCloudBrand
                  ? "cursor-pointer hover:text-primary"
                  : "cursor-pointer hover:text-blue-600",
              )}
              onClick={() =>
                data &&
                router.push(
                  `/knowledge/chunks?document_id=${encodeURIComponent(data.document_id || "")}&web_source_id=${encodeURIComponent(sourceId)}`,
                )
              }
            >
              <span className="min-w-0 truncate font-medium text-foreground">
                {value}
              </span>
            </button>
          </div>
        ),
      },
      {
        field: "source_url",
        headerName: "URL",
        sortable: true,
        flex: 2,
        minWidth: 240,
        cellRenderer: ({ value }: CustomCellRendererProps<File>) => (
          <a
            className="block truncate text-primary hover:underline"
            href={value}
            target="_blank"
            rel="noopener noreferrer"
          >
            {value}
          </a>
        ),
      },
      {
        field: "web_page_depth",
        headerName: "Depth",
        width: 88,
        sortable: true,
        cellClass: isCloudBrand ? "text-muted-foreground" : undefined,
      },
      {
        field: "size",
        headerName: "Size",
        ...(isCloudBrand ? { flex: 1, minWidth: 110 } : {}),
        sortable: true,
        valueFormatter: ({ value }) => (value ? formatFileSize(value) : "—"),
        cellClass: isCloudBrand ? "text-muted-foreground" : undefined,
      },
      {
        field: "chunkCount",
        headerName: "Chunks",
        ...(isCloudBrand ? { flex: 0.9, minWidth: 95 } : {}),
        sortable: true,
        valueFormatter: ({ value }) => value || "—",
        cellClass: isCloudBrand ? "text-muted-foreground" : undefined,
      },
      {
        field: "embedding_model",
        headerName: "Embedding model",
        ...(isCloudBrand ? { flex: 1.4 } : {}),
        minWidth: 200,
        sortable: true,
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
        minWidth: 120,
        sortable: true,
        cellRenderer: ({ value }: CustomCellRendererProps<File>) => (
          <StatusBadge status={value || "active"} />
        ),
      },
      {
        colId: "actions",
        headerName: "",
        width: 56,
        minWidth: 56,
        ...(isCloudBrand ? { maxWidth: 56 } : { initialFlex: 0 }),
        sortable: false,
        filter: false,
        resizable: false,
        suppressMovable: true,
        cellRenderer: ({ data }: CustomCellRendererProps<File>) =>
          data?.web_page_id ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="iconSm" aria-label="Page actions">
                  <MoreVertical className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onClick={() =>
                    router.push(
                      `/knowledge/chunks?document_id=${encodeURIComponent(data.document_id || "")}&web_source_id=${encodeURIComponent(sourceId)}`,
                    )
                  }
                >
                  View chunks
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() =>
                    action(
                      `/api/connectors/url/sources/${sourceId}/pages/${data.web_page_id}/sync`,
                    )
                  }
                >
                  Re-sync page
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onClick={() =>
                    action(
                      `/api/connectors/url/sources/${sourceId}/pages/${data.web_page_id}`,
                      "DELETE",
                    )
                  }
                >
                  Delete page
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null,
        cellStyle: {
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 0,
        },
      },
    ],
    [action, isCloudBrand, router, sourceId],
  );

  if (!source && sourceLoading) {
    return (
      <div className="p-8 text-muted-foreground">Loading website pages…</div>
    );
  }
  if (!source) return null;

  return (
    <div className="flex h-full flex-col">
      <header className="mb-6">
        <div className="mb-5 flex items-center gap-2 text-sm">
          <button
            type="button"
            className="text-primary hover:underline"
            onClick={() => router.push("/knowledge")}
          >
            Project knowledge
          </button>
          <span className="text-muted-foreground">/</span>
          <span className="text-foreground">{source.name}</span>
        </div>
        <div className="flex min-w-0 items-center gap-2">
          <KnowledgeUrlIcon className="size-5 text-foreground" />
          <h1 className="min-w-0 truncate text-3xl font-normal tracking-tight">
            {source.name}
          </h1>
        </div>
        <div className="ml-7 mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <a
            href={source.starting_url}
            target="_blank"
            rel="noopener noreferrer"
            className="max-w-full truncate text-primary hover:underline"
          >
            {source.starting_url}
          </a>
          <span aria-hidden="true" className="text-muted-foreground">
            ·
          </span>
          <span className="text-muted-foreground">
            {source.web_child_count ?? total} pages indexed
          </span>
          <span aria-hidden="true" className="text-muted-foreground">
            ·
          </span>
          <span className="text-muted-foreground">
            {formatLastSync(source.last_successful_sync_at)}
          </span>
        </div>
      </header>

      <KnowledgeSearchBar
        value={search}
        onSearch={setSearch}
        onClear={() => setSearch("")}
        placeholder="Search knowledge"
        rightActions={
          <Button
            type="button"
            variant={isCloudBrand ? "ghost" : "outline"}
            disabled={isSyncing}
            size={isCloudBrand ? "icon" : undefined}
            className={cn(
              isCloudBrand
                ? "h-auto flex-shrink-0 rounded-none hover:bg-accent hover:text-foreground"
                : "flex-shrink-0 rounded-lg",
            )}
            aria-label="Sync"
            onClick={syncSource}
          >
            <RefreshCw
              className={cn(
                "h-4 w-4",
                isCloudBrand ? "m-4" : "mr-2",
                isSyncing && !isCloudBrand && "animate-spin",
                isCloudBrand && "text-[var(--icon-primary)]",
              )}
            />
            {!isCloudBrand && (isSyncing ? "Syncing..." : "Sync")}
          </Button>
        }
      />

      <KnowledgeDataTable
        rows={pages}
        columnDefs={columnDefs}
        defaultColDef={defaultColDef}
        gridRef={gridRef}
        loading={sourceLoading || isPagesLoading}
        isCloudBrand={isCloudBrand}
        rowSelection="multiple"
        getRowId={({ data }) =>
          data.web_page_id || data.document_id || data.filename
        }
        onSortChanged={onSortChanged}
        emptyTitle="No crawled pages"
        emptyDescription="Pages will appear here as the website crawl completes."
      />

      <KnowledgePaginationFooter
        currentPage={currentPage}
        currentPageSize={currentPageSize}
        totalPages={Math.max(1, Math.ceil(total / currentPageSize))}
        serverTotal={total}
        isLoading={isPagesFetching}
        cursorCacheRef={cursorCacheRef}
        setCurrentPage={setCurrentPage}
        setCurrentPageSize={setCurrentPageSize}
      />
    </div>
  );
}
