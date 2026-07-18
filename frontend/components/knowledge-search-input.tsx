import { ArrowRight, Search, X } from "lucide-react";
import { type ChangeEvent, type FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { trackButton } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import { filterAccentClasses } from "./knowledge-filter-panel";

export type KnowledgeSearchInputProps = {
  /** Controlled value — when set with onSearch, skips global queryOverride. */
  value?: string;
  onSearch?: (query: string) => void;
  onClear?: () => void;
  placeholder?: string;
  /** Hide the selected-filter chip (file-scoped panels). */
  hideFilterChip?: boolean;
  /** Hide the submit arrow (live-filter / header search). */
  hideSubmit?: boolean;
  className?: string;
  inputClassName?: string;
};

function trackSearch(queryLength: number, hasFilter: boolean) {
  trackButton({
    CTA: "Search Knowledge",
    elementId: "search-knowledge-button",
    namespace: "knowledge",
    payload: { queryLength, hasFilter },
  });
}

export function KnowledgeSearchInput({
  value,
  onSearch,
  onClear,
  placeholder = "Search your documents...",
  hideFilterChip = false,
  hideSubmit = false,
  className,
  inputClassName,
}: KnowledgeSearchInputProps = {}) {
  const controlled = onSearch != null;
  const {
    selectedFilter,
    setSelectedFilter,
    parsedFilterData,
    queryOverride,
    setQueryOverride,
  } = useKnowledgeFilter();

  // Uncontrolled (knowledge page): draft until submit; sync when override changes.
  const [draft, setDraft] = useState(queryOverride || "");
  const [prevOverride, setPrevOverride] = useState(queryOverride);
  if (!controlled && queryOverride !== prevOverride) {
    setPrevOverride(queryOverride);
    setDraft(queryOverride || "");
  }

  const inputValue = controlled ? (value ?? "") : draft;

  const commitSearch = (raw: string) => {
    const next = raw.trim();
    trackSearch(next.length, Boolean(selectedFilter));
    if (controlled) {
      onSearch(next);
    } else {
      setQueryOverride(next);
    }
  };

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    commitSearch(inputValue);
  };

  const handleClear = () => {
    if (controlled) {
      onClear?.();
      onSearch("");
    } else {
      setDraft("");
      setQueryOverride("");
    }
  };

  const showClear = controlled ? Boolean(value) : Boolean(queryOverride);

  return (
    <form
      className={cn(
        "flex flex-1 max-w-[min(640px,100%)] min-w-[100px]",
        className,
      )}
      onSubmit={handleSubmit}
    >
      <div
        className={cn(
          "primary-input group/input min-h-10 !flex w-full items-center flex-nowrap focus-within:border-foreground transition-colors !p-[0.3rem]",
          inputClassName,
        )}
      >
        {!hideFilterChip && selectedFilter?.name && (
          <div
            title={selectedFilter.name}
            className={`flex items-center gap-1 h-full px-1.5 py-0.5 mr-1 rounded max-w-[25%] ${
              filterAccentClasses[parsedFilterData?.color || "zinc"]
            }`}
          >
            <span className="truncate text-xs font-medium">
              {selectedFilter.name}
            </span>
            <X
              aria-label="Remove filter"
              className="h-4 w-4 flex-shrink-0 cursor-pointer"
              onClick={() => setSelectedFilter(null)}
            />
          </div>
        )}
        <Search
          className="h-4 w-4 ml-1 flex-shrink-0 text-placeholder-foreground"
          strokeWidth={1.5}
        />
        <input
          className="bg-transparent w-full h-full ml-2 focus:outline-none focus-visible:outline-none font-mono placeholder:font-mono"
          name="search-query"
          id="search-query"
          type="text"
          placeholder={placeholder}
          value={inputValue}
          onChange={(e: ChangeEvent<HTMLInputElement>) => {
            const next = e.target.value;
            if (controlled) {
              // File-scoped panels filter as you type / paste.
              onSearch(next);
            } else {
              setDraft(next);
            }
          }}
        />
        {showClear && (
          <Button
            variant="ghost"
            className="h-full rounded-sm !px-1.5 !py-0"
            type="button"
            onClick={handleClear}
          >
            <X className="h-4 w-4" />
          </Button>
        )}
        {!hideSubmit && (
          <Button
            variant="ghost"
            className={cn(
              "h-full rounded-sm !px-1.5 !py-0 hidden group-focus-within/input:block",
              inputValue && "block",
            )}
            type="submit"
          >
            <ArrowRight className="h-4 w-4" />
          </Button>
        )}
      </div>
    </form>
  );
}
