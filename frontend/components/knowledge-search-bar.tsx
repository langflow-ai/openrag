import { Download, RefreshCw, X } from "lucide-react";
import { type ReactNode, useCallback, useState } from "react";
import { toast } from "sonner";
import { useRefreshOpenragDocs } from "@/app/api/mutations/useRefreshOpenragDocs";
import {
  type SyncAllPreviewResponse,
  useSyncAllConnectors,
  useSyncAllConnectorsPreview,
} from "@/app/api/mutations/useSyncConnector";
import { KnowledgeDropdown } from "@/components/knowledge-dropdown";
import { KnowledgeSearchInput } from "@/components/knowledge-search-input";
import { KnowledgeSearchToolbar } from "@/components/knowledge-search-toolbar";
import { RequirePermission } from "@/components/require-permission";
import { Button } from "@/components/ui/button";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { trackButton } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import { filterAccentClasses } from "./knowledge-filter-panel";
import { SyncConfirmDialog } from "./sync-confirm-dialog";

type KnowledgeSearchBarProps = {
  value?: string;
  onSearch?: (query: string) => void;
  onClear?: () => void;
  placeholder?: string;
  nonCloudPlaceholder?: string;
  rightActions?: ReactNode;
  selectedCount?: number;
  onDeleteSelected?: () => void;
};

export const KnowledgeSearchBar = ({
  value,
  onSearch,
  onClear,
  placeholder = "Search knowledge",
  nonCloudPlaceholder,
  rightActions,
  selectedCount = 0,
  onDeleteSelected,
}: KnowledgeSearchBarProps) => {
  const isCloudBrand = useIsCloudBrand();
  const controlled = onSearch != null;
  const {
    selectedFilter,
    setSelectedFilter,
    parsedFilterData,
    queryOverride,
    setQueryOverride,
  } = useKnowledgeFilter();

  const [searchQueryInput, setSearchQueryInput] = useState(queryOverride || "");
  const [prevQueryOverride, setPrevQueryOverride] = useState(queryOverride);
  if (!controlled && queryOverride !== prevQueryOverride) {
    setPrevQueryOverride(queryOverride);
    setSearchQueryInput(queryOverride);
  }

  const displayedValue = controlled ? (value ?? "") : searchQueryInput;

  const handleSearch = useCallback(() => {
    const next = displayedValue.trim();
    if (controlled) {
      onSearch(next);
    } else {
      setQueryOverride(next);
    }
  }, [controlled, displayedValue, onSearch, setQueryOverride]);

  const handleReset = useCallback(() => {
    if (controlled) {
      onClear?.();
      onSearch("");
    } else {
      setSearchQueryInput("");
      setQueryOverride("");
    }
  }, [controlled, onClear, onSearch, setQueryOverride]);

  const syncAllConnectorsMutation = useSyncAllConnectors();
  const syncAllPreviewMutation = useSyncAllConnectorsPreview();
  const refreshOpenragDocsMutation = useRefreshOpenragDocs();
  const [syncDialogOpen, setSyncDialogOpen] = useState(false);
  const [syncPreview, setSyncPreview] = useState<SyncAllPreviewResponse | null>(
    null,
  );

  const handleOpenSyncDialog = useCallback(async () => {
    setSyncPreview(null);
    setSyncDialogOpen(true);
    try {
      const preview = await syncAllPreviewMutation.mutateAsync();
      setSyncPreview(preview);
    } catch (error) {
      setSyncDialogOpen(false);
      toast.error(
        error instanceof Error ? error.message : "Failed to preview sync",
      );
    }
  }, [syncAllPreviewMutation]);

  const handleConfirmSync = useCallback(async () => {
    try {
      const result = await syncAllConnectorsMutation.mutateAsync();
      if (result.status === "no_files") {
        toast.info(
          result.message ||
            "No cloud files to sync. Add files from cloud connectors first.",
        );
      } else if (
        result.synced_connectors &&
        result.synced_connectors.length > 0
      ) {
        toast.success(
          `Sync started for ${result.synced_connectors.join(", ")}. Check task notifications for progress.`,
        );
      } else if (result.errors && result.errors.length > 0) {
        toast.error("Some connectors failed to sync");
      }
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to sync connectors",
      );
    }
  }, [syncAllConnectorsMutation]);

  const defaultRightActions = isCloudBrand ? (
    <>
      <Button
        type="button"
        variant="ghost"
        disabled={
          syncAllConnectorsMutation.isPending ||
          syncAllPreviewMutation.isPending
        }
        size="icon"
        className="h-auto flex-shrink-0 rounded-none hover:bg-accent hover:text-foreground"
        aria-label="Sync"
        onClick={handleOpenSyncDialog}
      >
        <RefreshCw className="m-4 h-4 w-4 text-[var(--icon-primary)]" />
      </Button>
      <RequirePermission perm="config:write">
        <Button
          type="button"
          variant="ghost"
          disabled={refreshOpenragDocsMutation.isPending}
          aria-label={
            refreshOpenragDocsMutation.isPending
              ? "Refreshing docs..."
              : "Fetch latest docs"
          }
          className="h-auto flex-shrink-0 gap-2 rounded-none px-3 text-sm hover:bg-accent hover:text-foreground"
          onClick={async () => {
            try {
              toast.info("Refreshing OpenRAG docs...");
              const result = await refreshOpenragDocsMutation.mutateAsync();
              toast.success(result.message);
            } catch (error) {
              toast.error(
                error instanceof Error
                  ? error.message
                  : "Failed to refresh OpenRAG docs",
              );
            }
          }}
        >
          <Download className="h-4 w-4 flex-shrink-0" />
          <span className="hidden lg:inline">
            {refreshOpenragDocsMutation.isPending
              ? "Refreshing docs..."
              : "Fetch latest docs"}
          </span>
        </Button>
      </RequirePermission>
      <div className="ml-auto">
        <KnowledgeDropdown />
      </div>
    </>
  ) : (
    <>
      <Button
        type="button"
        variant="outline"
        className="flex-shrink-0 rounded-lg"
        disabled={
          syncAllConnectorsMutation.isPending ||
          syncAllPreviewMutation.isPending
        }
        onClick={handleOpenSyncDialog}
      >
        {syncAllConnectorsMutation.isPending ||
        syncAllPreviewMutation.isPending ? (
          <>
            <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
            Syncing...
          </>
        ) : (
          <>
            <RefreshCw className="mr-2 h-4 w-4" />
            Sync
          </>
        )}
      </Button>
      <RequirePermission perm="config:write">
        <Button
          type="button"
          variant="outline"
          className="flex-shrink-0 rounded-lg"
          disabled={refreshOpenragDocsMutation.isPending}
          onClick={async () => {
            trackButton({
              CTA: "Fetch Latest Docs",
              elementId: "fetch-latest-docs-button",
              namespace: "knowledge",
            });
            try {
              toast.info("Refreshing OpenRAG docs...");
              const result = await refreshOpenragDocsMutation.mutateAsync();
              toast.success(result.message);
            } catch (error) {
              toast.error(
                error instanceof Error
                  ? error.message
                  : "Failed to refresh OpenRAG docs",
              );
            }
          }}
        >
          {refreshOpenragDocsMutation.isPending
            ? "Refreshing docs..."
            : "Fetch latest docs"}
        </Button>
      </RequirePermission>
      {selectedCount > 0 && (
        <Button
          type="button"
          variant="destructive"
          className="flex-shrink-0 rounded-lg"
          onClick={onDeleteSelected}
        >
          Delete
        </Button>
      )}
      <div className="ml-auto">
        <KnowledgeDropdown />
      </div>
    </>
  );

  return (
    <>
      <KnowledgeSearchToolbar
        value={displayedValue}
        onValueChange={controlled ? onSearch : setSearchQueryInput}
        onSubmit={handleSearch}
        onClear={handleReset}
        placeholder={placeholder}
        filter={
          !controlled && selectedFilter?.name ? (
            <div
              title={selectedFilter.name}
              className={cn(
                "flex h-full max-w-[200px] flex-shrink-0 items-center gap-1.5 border-r border-border px-2",
                filterAccentClasses[parsedFilterData?.color || "zinc"],
              )}
            >
              <span className="truncate text-xs font-medium">
                {selectedFilter.name}
              </span>
              <button
                type="button"
                aria-label="Remove filter"
                className="inline-flex h-4 w-4 flex-shrink-0 items-center justify-center opacity-80 transition-opacity hover:opacity-100"
                onClick={() => setSelectedFilter(null)}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : undefined
        }
        rightActions={rightActions ?? defaultRightActions}
        nonCloudSearch={
          controlled ? (
            <KnowledgeSearchInput
              value={displayedValue}
              onSearch={onSearch}
              onClear={handleReset}
              placeholder={nonCloudPlaceholder}
              hideFilterChip
            />
          ) : (
            <KnowledgeSearchInput />
          )
        }
      />
      {!controlled && (
        <SyncConfirmDialog
          open={syncDialogOpen}
          onOpenChange={setSyncDialogOpen}
          onConfirm={handleConfirmSync}
          isLoading={syncAllPreviewMutation.isPending || syncPreview === null}
          isSyncing={syncAllConnectorsMutation.isPending}
          isSyncAll
          orphansByType={syncPreview?.orphans_by_type}
          orphansAvailableByType={syncPreview?.orphans_available_by_type}
          updatesByType={syncPreview?.updates_by_type}
          updatesAvailableByType={syncPreview?.updates_available_by_type}
          syncedCountByType={syncPreview?.synced_count_by_type}
        />
      )}
    </>
  );
};
