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
}

export const DuplicateHandlingDialog: React.FC<
  DuplicateHandlingDialogProps
> = ({ open, onOpenChange, onOverwrite, isLoading = false }) => {
  const handleOverwrite = async () => {
    await onOverwrite();
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[450px]">
        <DialogHeader>
          <DialogTitle>Overwrite document</DialogTitle>
          <DialogDescription className="pt-2 text-muted-foreground">
            Overwriting will replace the existing document with another version.
            This can&apos;t be undone.
          </DialogDescription>
        </DialogHeader>

        <DialogFooter className="flex-row gap-2 justify-end">
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={isLoading}
            size="sm"
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="default"
            size="sm"
            onClick={handleOverwrite}
            disabled={isLoading}
            className="flex items-center gap-2 !bg-accent-amber-foreground hover:!bg-foreground text-primary-foreground"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Overwrite
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
