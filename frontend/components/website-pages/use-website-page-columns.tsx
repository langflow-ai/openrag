import { type ColDef } from "ag-grid-community";
import { type CustomCellRendererProps } from "ag-grid-react";
import { MoreVertical } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useMemo } from "react";
import type { File } from "@/app/api/queries/useGetSearchQuery";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { StatusBadge } from "@/components/ui/status-badge";
import { formatFileSize } from "@/lib/file-format";
import { cn } from "@/lib/utils";

export function useWebsitePageColumns({
  sourceId,
  isCloudBrand,
  onAction,
}: {
  sourceId: string;
  isCloudBrand: boolean;
  onAction(url: string, method?: string): Promise<void>;
}) {
  const router = useRouter();
  const viewChunks = useCallback(
    (documentId?: string) =>
      router.push(
        `/knowledge/chunks?document_id=${encodeURIComponent(documentId || "")}&web_source_id=${encodeURIComponent(sourceId)}`,
      ),
    [router, sourceId],
  );

  return useMemo<ColDef<File>[]>(
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
              onClick={() => data && viewChunks(data.document_id)}
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
                <DropdownMenuItem onClick={() => viewChunks(data.document_id)}>
                  View chunks
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() =>
                    onAction(
                      `/api/connectors/url/sources/${sourceId}/pages/${data.web_page_id}/sync`,
                    )
                  }
                >
                  Re-sync page
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onClick={() =>
                    onAction(
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
    [isCloudBrand, onAction, sourceId, viewChunks],
  );
}
