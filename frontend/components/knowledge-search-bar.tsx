import { ArrowRight, RefreshCw, Search, X } from "lucide-react";
import {
  type ChangeEvent,
  type FormEvent,
  useCallback,
  useEffect,
  useState,
} from "react";
import { toast } from "sonner";
import { useRefreshOpenragDocs } from "@/app/api/mutations/useRefreshOpenragDocs";
import { useSyncAllConnectors } from "@/app/api/mutations/useSyncConnector";
import { Button } from "@/components/ui/button";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { cn } from "@/lib/utils";
import { KnowledgeDropdown } from "./knowledge-dropdown";
import { filterAccentClasses } from "./knowledge-filter-panel";

export const KnowledgeSearchBar = () => {
  const {
    selectedFilter,
    setSelectedFilter,
    parsedFilterData,
    queryOverride,
    setQueryOverride,
  } = useKnowledgeFilter();

  const [searchQueryInput, setSearchQueryInput] = useState(queryOverride || "");

  const handleSearch = useCallback(
    (e?: FormEvent<HTMLFormElement>) => {
      if (e) e.preventDefault();
      setQueryOverride(searchQueryInput.trim());
    },
    [searchQueryInput, setQueryOverride],
  );

  const handleReset = useCallback(() => {
    setSearchQueryInput("");
    setQueryOverride("");
  }, [setQueryOverride]);

  useEffect(() => {
    setSearchQueryInput(queryOverride);
  }, [queryOverride]);

  const syncAllConnectorsMutation = useSyncAllConnectors();
  const refreshOpenragDocsMutation = useRefreshOpenragDocs();

  return (
    <form onSubmit={handleSearch} className={"flex w-full items-stretch"}>
      <div className="flex h-12 w-full overflow-hidden border border-border bg-card">
        {!!selectedFilter?.name && (
          <div
            title={selectedFilter.name}
            className={cn(
              "flex h-full flex-shrink-0 items-center gap-1.5 border-r border-border px-2 max-w-[200px]",
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
        )}

        <div className="flex h-full flex-shrink-0 items-center justify-center">
          <Search
            className="h-4 w-4 m-4 text-[var(--icon-secondary)]"
            strokeWidth={1.75}
          />
        </div>

        <div className="group/input flex min-w-0 flex-1 items-center">
          <input
            id="search-query"
            name="search-query"
            type="text"
            placeholder="Search knowledge"
            value={searchQueryInput}
            onChange={(e: ChangeEvent<HTMLInputElement>) =>
              setSearchQueryInput(e.target.value)
            }
            className="h-full w-full bg-transparent text-sm text-[hsl(var(--placeholder))] placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:ring-0"
          />
          {queryOverride && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={handleReset}
              className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          )}
          <Button
            variant="ghost"
            className="h-auto rounded-none hover:bg-accent hover:text-foreground p-2 hidden group-focus-within/input:block"
            type="submit"
          >
            <ArrowRight className="h-4 w-4 text-[var(--icon-primary)]" />
          </Button>
        </div>
        <Button
          type="button"
          variant="ghost"
          disabled={syncAllConnectorsMutation.isPending}
          size="icon"
          className="h-auto flex-shrink-0 rounded-none hover:bg-accent hover:text-foreground"
          aria-label="Sync"
          onClick={async () => {
            try {
              toast.info("Syncing all cloud connectors...");
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
                error instanceof Error
                  ? error.message
                  : "Failed to sync connectors",
              );
            }
          }}
        >
          <RefreshCw className="h-4 w-4 m-4 text-[var(--icon-primary)]" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={refreshOpenragDocsMutation.isPending}
          className="h-auto flex-shrink-0 rounded-none px-3 text-sm hover:bg-accent hover:text-foreground"
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
          {refreshOpenragDocsMutation.isPending
            ? "Refreshing docs..."
            : "Fetch latest docs"}
        </Button>
        <div className="ml-auto">
          <KnowledgeDropdown />
        </div>
      </div>
    </form>
  );
};
