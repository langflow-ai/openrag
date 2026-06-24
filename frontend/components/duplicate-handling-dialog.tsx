"use client";

import { RotateCcw } from "lucide-react";
import type React from "react";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { cn } from "@/lib/utils";
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
  duplicateNames?: string[];
}

const MAX_LISTED_DUPLICATES = 5;

export const DuplicateHandlingDialog = ({
  open,
  onOpenChange,
  onOverwrite,
  isLoading = false,
  duplicateLabel,
  duplicateCount,
  duplicateNames,
}: DuplicateHandlingDialogProps) => {
  const isCloudBrand = useIsCloudBrand();

  const handleOverwrite = async () => {
    await onOverwrite();
    onOpenChange(false);
  };

  const namesProvided = duplicateNames && duplicateNames.length > 0;
  const effectiveCount = namesProvided
    ? duplicateNames!.length
    : duplicateCount;

  const description =
    typeof effectiveCount === "number"
      ? effectiveCount === 1
        ? "1 duplicate document already exists. Overwriting will replace the existing document version. This can't be undone."
        : `${effectiveCount} duplicate documents already exist. Overwriting will replace the existing document versions. This can't be undone.`
      : duplicateLabel
        ? `A document named "${duplicateLabel}" already exists. Overwriting will replace the existing document version. This can't be undone.`
        : "Overwriting will replace the existing document with another version. This can't be undone.";
  const overwriteLabel =
    typeof effectiveCount === "number" ? "Overwrite duplicates" : "Overwrite";
  const cancelLabel =
    typeof effectiveCount === "number"
      ? "Skip duplicates & continue"
      : "Cancel";

  const visibleNames = namesProvided
    ? duplicateNames!.slice(0, MAX_LISTED_DUPLICATES)
    : [];
  const remainingCount = namesProvided
    ? duplicateNames!.length - visibleNames.length
    : 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>Overwrite document</DialogTitle>
          <DialogDescription className="pt-2 text-muted-foreground">
            {description}
          </DialogDescription>
        </DialogHeader>

        {namesProvided && (
          <ul className="text-sm text-muted-foreground list-disc pl-5 space-y-0.5">
            {visibleNames.map((name) => (
              <li key={name} className="break-all">
                {name}
              </li>
            ))}
            {remainingCount > 0 && (
              <li className="list-none italic">… and {remainingCount} more</li>
            )}
          </ul>
        )}

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
            className={cn(
              "flex items-center gap-2 whitespace-nowrap text-primary-foreground",
              isCloudBrand
                ? "rounded-none !bg-[hsl(var(--ibm-overwrite-button))] hover:!bg-[hsl(var(--ibm-overwrite-button-hover))]"
                : "!bg-accent-amber-foreground hover:!bg-foreground",
            )}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            {overwriteLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
