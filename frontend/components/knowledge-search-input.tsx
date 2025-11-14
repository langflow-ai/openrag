import { ArrowRight, Search, X } from "lucide-react";
import {
  type ChangeEvent,
  type FormEvent,
  useCallback,
  useEffect,
  useState,
} from "react";
import { Button } from "@/components/ui/button";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { cn } from "@/lib/utils";
import { filterAccentClasses } from "./knowledge-filter-panel";

export const KnowledgeSearchInput = () => {
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

  // Reset the query text when the selected filter changes
  useEffect(() => {
    setSearchQueryInput(queryOverride);
  }, [queryOverride]);

  return (
    <form
      className="flex flex-1 max-w-[min(640px,100%)] min-w-[100px]"
      onSubmit={handleSearch}
    >
      <div className="primary-input group/input min-h-10 !flex items-center flex-nowrap focus-within:border-foreground transition-colors !p-[0.3rem]">
        {selectedFilter?.name && (
          <div
            title={selectedFilter?.name}
            className={`flex items-center gap-1 h-full px-1.5 py-0.5 mr-1 rounded max-w-[25%] ${
              filterAccentClasses[parsedFilterData?.color || "zinc"]
            }`}
          >
            <span className="truncate text-xs font-medium">
              {selectedFilter?.name}
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
          placeholder="Search your documents..."
          value={searchQueryInput}
          onChange={(e: ChangeEvent<HTMLInputElement>) =>
            setSearchQueryInput(e.target.value)
          }
        />
        {queryOverride && (
          <Button
            variant="ghost"
            className="h-full rounded-sm !px-1.5 !py-0"
            type="button"
            onClick={() => {
              setSearchQueryInput("");
              setQueryOverride("");
            }}
          >
            <X className="h-4 w-4" />
          </Button>
        )}
        <Button
          variant="ghost"
          className={cn(
            "h-full rounded-sm !px-1.5 !py-0 hidden group-focus-within/input:block",
            searchQueryInput && "block",
          )}
          type="submit"
        >
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </form>
  );
};
