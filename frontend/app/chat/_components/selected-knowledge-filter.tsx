import { X } from "lucide-react";
import { filterAccentClasses } from "@/components/knowledge-filter-panel";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { FilterColor } from "@/lib/filter-constants";
import { queryDataRestrictsChat } from "@/lib/filter-normalization";
import type { KnowledgeFilterData } from "../_types/types";

export const TABLE_ONLY_FILTER_TOOLTIP =
  "Applies only to the Knowledge table: no sources, types, owners, connectors or dates selected.";

interface SelectedKnowledgeFilterProps {
  selectedFilter: KnowledgeFilterData;
  parsedFilterData: { color?: FilterColor } | null;
  onClear: () => void;
}

export const SelectedKnowledgeFilter = ({
  selectedFilter,
  parsedFilterData,
  onClear,
}: SelectedKnowledgeFilterProps) => {
  // A filter edited after it was picked can stop restricting chat.
  const tableOnly = !queryDataRestrictsChat(selectedFilter.query_data);

  return (
    <div
      className={`flex min-w-0 items-center gap-1 h-full px-1.5 py-0.5 mr-1 rounded max-w-[25%] ${
        tableOnly
          ? "bg-muted text-muted-foreground opacity-60"
          : filterAccentClasses[parsedFilterData?.color || "zinc"]
      }`}
      data-testid={`selected-knowledge-filter`}
    >
      {tableOnly ? (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <span
                className="truncate"
                tabIndex={0}
                aria-description={TABLE_ONLY_FILTER_TOOLTIP}
              >
                {selectedFilter.name}
              </span>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-56">
              {TABLE_ONLY_FILTER_TOOLTIP}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : (
        <span className="truncate">{selectedFilter.name}</span>
      )}
      <button
        type="button"
        onClick={onClear}
        className="ml-0.5 rounded-full p-0.5 shrink-0"
        aria-label="Clear selected filter"
        data-testid="clear-selected-filter"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
};
