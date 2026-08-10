"use client";

import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface BulkDeleteButtonProps {
  count: number;
  onDelete: () => void;
  isDeleting: boolean;
}

export const BulkDeleteButton = ({
  count,
  onDelete,
  isDeleting,
}: BulkDeleteButtonProps) => {
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      disabled={count === 0 || isDeleting}
      onClick={onDelete}
      data-testid="bulk-delete-confirm"
      className="w-full !bg-transparent !border-red-600 text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30 
        disabled:opacity-100 disabled:!border-red-200 disabled:text-red-200 dark:disabled:!border-red-900 dark:disabled:text-red-900"
    >
      <Trash2 className="mr-2 h-4 w-4" />
      Delete {count} chats
    </Button>
  );
};
