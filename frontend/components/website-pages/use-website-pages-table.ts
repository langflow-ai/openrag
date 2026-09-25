import { type ColumnState } from "ag-grid-community";
import { type AgGridReact } from "ag-grid-react";
import { type RefObject, useCallback, useMemo, useState } from "react";
import {
  EMPTY_SEARCH_RESULT,
  type File,
  type SearchResult,
  useGetSearchQuery,
} from "@/app/api/queries/useGetSearchQuery";
import { SEARCH_CONSTANTS } from "@/lib/constants";

export function useWebsitePagesTable(
  sourceId: string,
  gridRef: RefObject<AgGridReact<File> | null>,
) {
  const [search, setSearch] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [currentPageSize, setCurrentPageSize] = useState(25);
  const [sortBy, setSortBy] = useState("filename");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");

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

  const updateSearch = useCallback((value: string) => {
    setSearch(value);
    setCurrentPage(1);
  }, []);

  const onSortChanged = useCallback(() => {
    const state: ColumnState | undefined = gridRef.current?.api
      .getColumnState()
      .find((column) => column.sort != null);
    setSortBy(state?.colId || "filename");
    setSortOrder(state?.sort === "desc" ? "desc" : "asc");
    setCurrentPage(1);
  }, [gridRef]);

  return {
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
  };
}
