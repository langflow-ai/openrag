"use client";

import { type ColDef } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import type { File } from "@/app/api/queries/useGetSearchQuery";
import { KnowledgeDataTable } from "@/components/knowledge-data-table";
import { KnowledgePaginationFooter } from "@/components/knowledge-pagination-footer";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { useWebsitePageColumns } from "./website-pages/use-website-page-columns";
import { useWebsitePagesTable } from "./website-pages/use-website-pages-table";
import { useWebsiteSource } from "./website-pages/use-website-source";
import { WebsitePagesHeader } from "./website-pages/website-pages-header";
import { WebsitePagesToolbar } from "./website-pages/website-pages-toolbar";

export function WebsitePagesView({ sourceId }: { sourceId: string }) {
  const router = useRouter();
  const isCloudBrand = useIsCloudBrand();
  const gridRef = useRef<AgGridReact<File>>(null);
  const cursorCacheRef = useRef<Map<number, Record<string, unknown>>>(null!);
  if (!cursorCacheRef.current) {
    cursorCacheRef.current = new Map();
  }
  const { source, sourceLoading, reload } = useWebsiteSource(sourceId);
  const {
    currentPage,
    currentPageSize,
    isPagesFetching,
    isPagesLoading,
    onSortChanged,
    pages,
    refetchPages,
    search,
    setCurrentPage,
    setCurrentPageSize,
    total,
    updateSearch,
  } = useWebsitePagesTable(sourceId, gridRef);
  const [isSyncing, setIsSyncing] = useState(false);

  const action = useCallback(
    async (url: string, method = "POST") => {
      const response = await fetch(url, { method });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        toast.error(data.detail || data.error || "Action failed");
        return;
      }
      toast.success(method === "DELETE" ? "Page disabled" : "Sync started");
      void Promise.all([reload(), refetchPages()]);
    },
    [refetchPages, reload],
  );

  const syncSource = async () => {
    setIsSyncing(true);
    try {
      await action(`/api/connectors/url/sources/${sourceId}/sync`);
    } finally {
      setIsSyncing(false);
    }
  };

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
  const columnDefs = useWebsitePageColumns({
    sourceId,
    isCloudBrand,
    onAction: action,
  });

  if (!source && sourceLoading) {
    return (
      <div className="p-8 text-muted-foreground">Loading website pages…</div>
    );
  }
  if (!source) return null;

  return (
    <div className="flex h-full flex-col">
      <WebsitePagesHeader
        source={source}
        pageCount={total}
        onNavigateBack={() => router.push("/knowledge")}
      />
      <WebsitePagesToolbar
        search={search}
        onSearch={updateSearch}
        isCloudBrand={isCloudBrand}
        isSyncing={isSyncing}
        onSync={syncSource}
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
