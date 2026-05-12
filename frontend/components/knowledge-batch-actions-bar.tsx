import { X } from "lucide-react";

import { usePermissions } from "@/hooks/use-permissions";

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
  const { canAny } = usePermissions();
  const canDelete = canAny(["knowledge:delete:own", "knowledge:delete:any"]);
  return (
    <div className="flex h-12 w-full items-stretch bg-primary text-primary-foreground">
      <button
        type="button"
        aria-label="Cancel selection"
        onClick={onCancel}
        className="flex h-full w-12 flex-shrink-0 items-center justify-center border-r border-primary-foreground/20 transition-colors hover:bg-primary-foreground/10"
      >
        <X className="h-4 w-4" />
      </button>
      <span className="flex items-center px-4 text-sm font-medium">
        {selectedCount} item{selectedCount !== 1 ? "s" : ""} selected
      </span>
      <div className="ml-auto flex items-stretch">
        <button
          type="button"
          onClick={onDelete}
          disabled={!canDelete}
          title={
            canDelete
              ? undefined
              : "You do not have permission to delete documents"
          }
          className="flex h-full items-center px-4 text-sm font-medium transition-colors hover:bg-primary-foreground/10 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Trash2 className="h-4 w-4" />
          Delete
        </button>
      </div>
    </div>
  );
};
