"use client";

import { RotateCcw } from "lucide-react";
import type React from "react";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";

interface DuplicateHandlingDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onOverwrite: () => void | Promise<void>;
  isLoading?: boolean;
  duplicateLabel?: string;
  duplicateCount?: number;
}

export const DuplicateHandlingDialog: React.FC<
  DuplicateHandlingDialogProps
> = ({
  open,
  onOpenChange,
  onOverwrite,
  isLoading = false,
  duplicateLabel,
  duplicateCount,
}) => {
  const handleOverwrite = async () => {
    await onOverwrite();
    onOpenChange(false);
  };

  const description =
    typeof duplicateCount === "number"
      ? duplicateCount === 1
        ? "1 duplicate document already exists. Overwriting will replace the existing document version. This can't be undone."
        : `${duplicateCount} duplicate documents already exist. Overwriting will replace the existing document versions. This can't be undone.`
      : duplicateLabel
        ? `A document named "${duplicateLabel}" already exists. Overwriting will replace the existing document version. This can't be undone.`
        : "Overwriting will replace the existing document with another version. This can't be undone.";
  const overwriteLabel =
    typeof duplicateCount === "number" ? "Overwrite duplicates" : "Overwrite";
  const cancelLabel =
    typeof duplicateCount === "number"
      ? "Skip duplicates & continue"
      : "Cancel";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>Overwrite document</DialogTitle>
          <DialogDescription className="pt-2 text-muted-foreground">
            {description}
          </DialogDescription>
        </DialogHeader>

        <DialogFooter className="flex-row gap-2 justify-end">
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={isLoading}
            size="sm"
            className="whitespace-nowrap"
          >
            {cancelLabel}
          </Button>
          <Button
            type="button"
            variant="default"
            size="sm"
            onClick={handleOverwrite}
            disabled={isLoading}
            className="flex items-center gap-2 whitespace-nowrap !bg-accent-amber-foreground hover:!bg-foreground text-primary-foreground"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            {overwriteLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
