import React from "react";

export interface KnowledgePaginationFooterProps {
  currentPage: number;
  currentPageSize: number;
  totalPages: number;
  serverTotal: number;
  cursorCacheRef: React.RefObject<Map<number, Record<string, unknown>>>;
  setCurrentPage: React.Dispatch<React.SetStateAction<number>>;
  setCurrentPageSize: React.Dispatch<React.SetStateAction<number>>;
}

export function KnowledgePaginationFooter({
  currentPage,
  currentPageSize,
  totalPages,
  serverTotal,
  cursorCacheRef,
  setCurrentPage,
  setCurrentPageSize,
}: KnowledgePaginationFooterProps) {
  const atFirst = currentPage <= 1;
  const atLast = currentPage >= totalPages;

  return (
    <div
      className="flex items-center justify-end gap-4 border-t border-border bg-background px-3 text-sm text-muted-foreground"
      style={{ height: "var(--ag-pagination-panel-height, 48px)" }}
    >
      {/* page size */}
      <label className="flex items-center gap-1.5 whitespace-nowrap">
        Page Size:
        <select
          value={currentPageSize}
          onChange={(e) => {
            cursorCacheRef.current = new Map();
            setCurrentPageSize(Number(e.target.value));
            setCurrentPage(1);
          }}
          className="cursor-pointer rounded-none border border-border bg-background px-1 py-0.5 text-sm text-muted-foreground"
        >
          {[10, 25, 50, 100].map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>

      {/* row summary */}
      <span className="whitespace-nowrap">
        {serverTotal === 0
          ? `0 of 0`
          : `${(currentPage - 1) * currentPageSize + 1} to ${Math.min(
              currentPage * currentPageSize,
              serverTotal,
            )} of ${serverTotal}`}
      </span>

      {/* nav buttons */}
      <div className="flex items-center">
        <button
          type="button"
          aria-label="Back to first page"
          aria-disabled={atFirst}
          disabled={atFirst}
          onClick={() => {
            if (!atFirst) {
              cursorCacheRef.current = new Map();
              setCurrentPage(1);
            }
          }}
          className="-mr-2 flex h-10 w-10 items-center justify-center rounded text-lg leading-none disabled:cursor-default disabled:opacity-40"
        >
          <span className="pointer-events-none">«</span>
        </button>
        <button
          type="button"
          aria-label="Previous page"
          aria-disabled={atFirst}
          disabled={atFirst}
          onClick={() => {
            if (!atFirst) setCurrentPage((p) => p - 1);
          }}
          className="flex h-10 w-10 items-center justify-center rounded text-lg leading-none disabled:cursor-default disabled:opacity-40"
        >
          <span className="pointer-events-none">‹</span>
        </button>
        <span className="whitespace-nowrap px-2">
          Page {currentPage} of {totalPages}
        </span>
        <button
          type="button"
          aria-label="Next page"
          aria-disabled={atLast}
          disabled={atLast}
          onClick={() => {
            if (!atLast) setCurrentPage((p) => p + 1);
          }}
          className="flex h-10 w-10 items-center justify-center rounded text-lg leading-none disabled:cursor-default disabled:opacity-40"
        >
          <span className="pointer-events-none">›</span>
        </button>
      </div>
    </div>
  );
}
