"use client";

import { type ColDef } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useRef } from "react";
import { toast } from "sonner";
import {
  useDeleteWebsiteSourcePageMutation,
  useSyncWebsiteSourceMutation,
} from "@/app/api/mutations/useWebsiteSourceMutation";
import type { File } from "@/app/api/queries/useGetSearchQuery";
import { useGetWebsiteSourceQuery } from "@/app/api/queries/useGetWebsiteSourceQuery";
import { KnowledgeDataTable } from "@/components/knowledge-data-table";
import { KnowledgePaginationFooter } from "@/components/knowledge-pagination-footer";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { useWebsitePageColumns } from "./website-pages/use-website-page-columns";
import { useWebsitePagesTable } from "./website-pages/use-website-pages-table";
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
  const { data: source, isLoading: sourceLoading } =
    useGetWebsiteSourceQuery(sourceId);
  const {
    currentPage,
    currentPageSize,
    isPagesFetching,
    isPagesLoading,
    onSortChanged,
    pages,
    search,
    setCurrentPage,
    setCurrentPageSize,
    total,
    updateSearch,
  } = useWebsitePagesTable(sourceId, gridRef);
  const syncWebsiteSourceMutation = useSyncWebsiteSourceMutation();
  const deleteWebsiteSourcePageMutation = useDeleteWebsiteSourcePageMutation();

  const action = useCallback(
    async (pageId?: string, operation: "sync" | "delete" = "sync") => {
      try {
        if (operation === "delete") {
          await deleteWebsiteSourcePageMutation.mutateAsync({
            sourceId,
            pageId,
          });
          toast.success("Page disabled");
        } else {
          await syncWebsiteSourceMutation.mutateAsync({ sourceId, pageId });
          toast.success("Sync started");
        }
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Action failed");
      }
    },
    [deleteWebsiteSourcePageMutation, sourceId, syncWebsiteSourceMutation],
  );

  const syncSource = () => action();

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
        isSyncing={syncWebsiteSourceMutation.isPending}
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
