"use client";

import {
  type ColDef,
  type GetRowIdParams,
  themeQuartz,
} from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import type { RefObject } from "react";
import { cn } from "@/lib/utils";
import "@/components/AgGrid/registerAgGridModules";
import "@/components/AgGrid/agGridStyles.css";

export interface KnowledgeDataTableProps<T> {
  rows: T[];
  columnDefs: ColDef<T>[];
  defaultColDef: ColDef<T>;
  gridRef?: RefObject<AgGridReact<T> | null>;
  loading?: boolean;
  isCloudBrand?: boolean;
  rowSelection?: "single" | "multiple";
  getRowId: (params: GetRowIdParams<T>) => string;
  isRowSelectable?: (params: { data?: T }) => boolean;
  onGridReady?: () => void;
  onGridPreDestroyed?: () => void;
  onSelectionChanged?: () => void;
  onSortChanged?: () => void;
  emptyTitle?: string;
  emptyDescription?: string;
}

/**
 * Shared Knowledge AG Grid shell. Column factories stay with their owning
 * surface; grid sizing, theme, loading, focus behaviour and empty states do not.
 */
export function KnowledgeDataTable<T>({
  rows,
  columnDefs,
  defaultColDef,
  gridRef,
  loading = false,
  isCloudBrand = false,
  rowSelection,
  getRowId,
  isRowSelectable,
  onGridReady,
  onGridPreDestroyed,
  onSelectionChanged,
  onSortChanged,
  emptyTitle = "No knowledge",
  emptyDescription = "Add files from local or your preferred cloud.",
}: KnowledgeDataTableProps<T>) {
  return (
    <div className="flex-1 min-h-0 overflow-hidden">
      <AgGridReact<T>
        className={cn("h-full w-full", isCloudBrand && "border")}
        columnDefs={columnDefs}
        defaultColDef={defaultColDef}
        loading={loading}
        ref={gridRef}
        theme={themeQuartz.withParams({ browserColorScheme: "inherit" })}
        rowData={rows}
        rowSelection={rowSelection}
        rowMultiSelectWithClick={false}
        suppressRowClickSelection={rowSelection === "multiple"}
        getRowId={getRowId}
        isRowSelectable={isRowSelectable}
        domLayout="normal"
        onGridReady={onGridReady}
        onGridPreDestroyed={onGridPreDestroyed}
        onSelectionChanged={onSelectionChanged}
        onSortChanged={onSortChanged}
        {...(isCloudBrand ? { headerHeight: 64, rowHeight: 64 } : {})}
        noRowsOverlayComponent={() => (
          <div className="pb-[45px] text-center">
            <div className="text-lg font-semibold text-primary">
              {emptyTitle}
            </div>
            <div className="mt-1 text-sm text-muted-foreground">
              {emptyDescription}
            </div>
          </div>
        )}
      />
    </div>
  );
}
