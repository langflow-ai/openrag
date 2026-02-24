"use client";

import React, { ReactNode } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { Button } from "./ui/button";
import { AlertTriangle } from "lucide-react";

/**
 * Formats a list of files to be deleted, truncating if necessary.
 * @param files - Array of files with a `filename` property
 * @param maxVisible - Maximum number of items to show before truncating (default: 5)
 * @returns Formatted string with bullet points, truncated if needed
 */
export function formatFilesToDelete(
  files: Array<{ filename: string }>,
  maxVisible = 5,
): ReactNode {
  const visibleFiles = files.slice(0, maxVisible);
  const remainingCount = files.length - maxVisible;
  return (
    <ul className="list-disc list-inside max-w-[29rem] sm:max-w-[calc(425px-3rem)]">
      {visibleFiles.map((file) => <li className="my-2 truncate">{file.filename}</li>)}
      {remainingCount > 0 ? <li>&hellip; and {remainingCount} more document{
        remainingCount > 1 ? "s" : ""
      }</li> : "" }
    </ul>
  );
}

interface DeleteConfirmationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  description?: string;
  confirmText?: string;
  cancelText?: string;
  onConfirm: () => void | Promise<void>;
  isLoading?: boolean;
  variant?: "destructive" | "default";
  children?: ReactNode;
}

export const DeleteConfirmationDialog: React.FC<
  DeleteConfirmationDialogProps
> = ({
  open,
  onOpenChange,
  title = "Are you sure?",
  description = "This action cannot be undone.",
  confirmText = "Confirm",
  cancelText = "Cancel",
  onConfirm,
  isLoading = false,
  variant = "destructive",
  children,
}) => {
  const handleConfirm = async () => {
    try {
      await onConfirm();
    } finally {
      // Only close if not in loading state (let the parent handle this)
      if (!isLoading) {
        onOpenChange(false);
      }
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <div className="flex items-center gap-3">
            {variant === "destructive" && (
              <AlertTriangle className="h-6 w-6 text-destructive" />
            )}
            <DialogTitle>{title}</DialogTitle>
          </div>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="text-sm text-muted-foreground">
          {children}
        </div>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isLoading}
          >
            {cancelText}
          </Button>
          <Button
            type="button"
            variant={variant}
            onClick={handleConfirm}
            loading={isLoading}
            disabled={isLoading}
          >
            {confirmText}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
