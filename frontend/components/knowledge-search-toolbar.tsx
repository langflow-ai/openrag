import { ArrowRight, Search, X } from "lucide-react";
import type { ChangeEvent, FormEvent, ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { cn } from "@/lib/utils";

type KnowledgeSearchToolbarProps = {
  value: string;
  onValueChange: (value: string) => void;
  onSubmit: () => void;
  onClear: () => void;
  placeholder?: string;
  filter?: ReactNode;
  rightActions?: ReactNode;
  nonCloudSearch: ReactNode;
};

/**
 * Shared Knowledge search surface. The input body and outer layout are fixed;
 * each page supplies only the actions that belong on the right edge.
 */
export function KnowledgeSearchToolbar({
  value,
  onValueChange,
  onSubmit,
  onClear,
  placeholder = "Search knowledge",
  filter,
  rightActions,
  nonCloudSearch,
}: KnowledgeSearchToolbarProps) {
  const isCloudBrand = useIsCloudBrand();

  if (!isCloudBrand) {
    return (
      <div className="mb-6 flex flex-shrink-0 flex-wrap-reverse items-center gap-3">
        {nonCloudSearch}
        {rightActions}
      </div>
    );
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit();
  };

  return (
    <form onSubmit={handleSubmit} className="flex w-full items-stretch">
      <div className="flex h-12 w-full overflow-hidden border border-border bg-card">
        {filter}
        <div className="flex h-full flex-shrink-0 items-center justify-center">
          <Search
            className="m-4 h-4 w-4 text-[var(--icon-secondary)]"
            strokeWidth={1.75}
          />
        </div>
        <div className="group/input flex min-w-0 flex-1 items-center">
          <input
            id="search-query"
            name="search-query"
            type="text"
            placeholder={placeholder}
            value={value}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              onValueChange(event.target.value)
            }
            className="h-full w-full bg-transparent text-sm text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:ring-0"
          />
          {value && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={onClear}
              className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          )}
          <Button
            variant="ghost"
            className={cn(
              "hidden h-auto rounded-none p-2 hover:bg-accent hover:text-foreground group-focus-within/input:block",
              value && "block",
            )}
            type="submit"
          >
            <ArrowRight className="h-4 w-4 text-[var(--icon-primary)]" />
          </Button>
        </div>
        {rightActions}
      </div>
    </form>
  );
}
