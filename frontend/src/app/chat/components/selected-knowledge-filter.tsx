import { X } from "lucide-react";
import type { KnowledgeFilterData } from "../types";
import { filterAccentClasses } from "@/components/knowledge-filter-panel";
import type { FilterColor } from "@/components/filter-icon-popover";

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
    <span
      className={`inline-flex items-center p-1 rounded-sm text-xs font-medium transition-colors ${
        filterAccentClasses[parsedFilterData?.color || "zinc"]
      }`}
    >
      {selectedFilter.name}
      <button
        type="button"
        onClick={onClear}
        className="ml-0.5 rounded-full p-0.5"
      >
        <X className="h-4 w-4" />
      </button>
    </span>
  );
};
