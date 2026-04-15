import { X } from "lucide-react";
import type { FilterColor } from "@/components/filter-icon-popover";
import { filterAccentClasses } from "@/components/knowledge-filter-panel";
import type { KnowledgeFilterData } from "../_types/types";

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
  return (
    <div
      className={`flex min-w-0 items-center gap-1 h-full px-1.5 py-0.5 mr-1 rounded max-w-[25%] ${
        filterAccentClasses[parsedFilterData?.color || "zinc"]
      }`}
      data-testid={`selected-knowledge-filter`}
    >
      <span className="truncate">{selectedFilter.name}</span>
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
