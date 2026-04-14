import { X } from "lucide-react";

interface KnowledgeBatchActionsBarProps {
  selectedCount: number;
  onDelete: () => void;
  onCancel: () => void;
}

export const KnowledgeBatchActionsBar = ({
  selectedCount,
  onDelete,
  onCancel,
}: KnowledgeBatchActionsBarProps) => {
  return (
    <div className="flex h-12 w-full items-stretch bg-primary text-primary-foreground">
      <span className="flex items-center px-4 text-sm font-medium">
        {selectedCount} item{selectedCount !== 1 ? "s" : ""} selected
      </span>
      <div className="ml-auto flex items-stretch">
        <button
          type="button"
          onClick={onDelete}
          className="flex h-full items-center px-4 text-sm font-medium transition-colors hover:bg-primary-foreground/10"
        >
          Delete
        </button>
        <span className="self-center h-4 w-px bg-primary-foreground" />
        <button
          type="button"
          aria-label="Cancel selection"
          onClick={onCancel}
          className="flex h-full w-12 flex-shrink-0 items-center justify-center transition-colors hover:bg-primary-foreground/10"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
};
