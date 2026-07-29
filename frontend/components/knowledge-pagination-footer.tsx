import React from "react";

function pageBtnStyle(disabled: boolean): React.CSSProperties {
  return {
    width: 40,
    height: 40,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    lineHeight: 1,
    padding: 0,
    background: "none",
    border: "none",
    borderRadius: 4,
    cursor: disabled ? "default" : "pointer",
    opacity: disabled ? 0.4 : 1,
    fontSize: 18,
    color: "inherit",
    userSelect: "none",
  };
}

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
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "flex-end",
        gap: 16,
        height: "var(--ag-pagination-panel-height, 48px)",
        paddingInline: "calc(var(--ag-grid-size, 4px) * 3)",
        borderTop: "1px solid var(--ag-border-color, hsl(var(--border)))",
        backgroundColor: "var(--ag-background-color, hsl(var(--background)))",
        color: "var(--ag-foreground-color, hsl(var(--muted-foreground)))",
        fontSize: "var(--ag-font-size, 14px)",
        fontFamily: "var(--ag-font-family, inherit)",
      }}
    >
      {/* page size */}
      <label
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          whiteSpace: "nowrap",
        }}
      >
        Page Size:
        <select
          value={currentPageSize}
          onChange={(e) => {
            cursorCacheRef.current = new Map();
            setCurrentPageSize(Number(e.target.value));
            setCurrentPage(1);
          }}
          style={{
            background: "var(--ag-background-color, hsl(var(--background)))",
            color: "var(--ag-foreground-color, hsl(var(--muted-foreground)))",
            border: "1px solid var(--ag-border-color, hsl(var(--border)))",
            borderRadius: "var(--ag-border-radius, 0px)",
            fontSize: "var(--ag-font-size, 14px)",
            fontFamily: "var(--ag-font-family, inherit)",
            padding: "2px 4px",
            cursor: "pointer",
          }}
        >
          {[10, 25, 50, 100].map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>

      {/* row summary */}
      <span style={{ whiteSpace: "nowrap" }}>
        {`${(currentPage - 1) * currentPageSize + 1} to ${Math.min(
          currentPage * currentPageSize,
          serverTotal,
        )} of ${serverTotal}`}
      </span>

      {/* nav buttons */}
      <div style={{ display: "flex", alignItems: "center", gap: 0 }}>
        <button
          type="button"
          aria-label="Back to first page"
          aria-disabled={currentPage <= 1}
          disabled={currentPage <= 1}
          style={{ ...pageBtnStyle(currentPage <= 1), marginRight: -8 }}
          onClick={() => {
            if (currentPage > 1) {
              cursorCacheRef.current = new Map();
              setCurrentPage(1);
            }
          }}
        >
          <span style={{ pointerEvents: "none" }}>«</span>
        </button>
        <button
          type="button"
          aria-label="Previous page"
          aria-disabled={currentPage <= 1}
          disabled={currentPage <= 1}
          style={pageBtnStyle(currentPage <= 1)}
          onClick={() => {
            if (currentPage > 1) setCurrentPage((p) => p - 1);
          }}
        >
          <span style={{ pointerEvents: "none" }}>‹</span>
        </button>
        <span style={{ padding: "0 8px", whiteSpace: "nowrap" }}>
          Page {currentPage} of {totalPages}
        </span>
        <button
          type="button"
          aria-label="Next page"
          aria-disabled={currentPage >= totalPages}
          disabled={currentPage >= totalPages}
          style={pageBtnStyle(currentPage >= totalPages)}
          onClick={() => {
            if (currentPage < totalPages) setCurrentPage((p) => p + 1);
          }}
        >
          <span style={{ pointerEvents: "none" }}>›</span>
        </button>
      </div>
    </div>
  );
}
