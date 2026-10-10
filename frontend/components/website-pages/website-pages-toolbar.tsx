import { RefreshCw } from "lucide-react";
import { KnowledgeSearchBar } from "@/components/knowledge-search-bar";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function WebsitePagesToolbar({
  search,
  onSearch,
  isCloudBrand,
  isSyncing,
  onSync,
}: {
  search: string;
  onSearch(value: string): void;
  isCloudBrand: boolean;
  isSyncing: boolean;
  onSync(): void;
}) {
  return (
    <KnowledgeSearchBar
      value={search}
      onSearch={onSearch}
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
          onClick={onSync}
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
  );
}
