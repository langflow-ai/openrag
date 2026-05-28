"use client";

import {
  ALL_TASK_STATUS_CATEGORIES,
  type TaskFileStatusCategory,
} from "@/lib/task-utils";
import { cn } from "@/lib/utils";
import { CATEGORY_CHIPS } from "./constants";

interface TaskDialogCategoryChipsProps {
  isCloudBrand: boolean;
  counts: Record<TaskFileStatusCategory, number> | null;
  statusCategory: string;
  onStatusCategoryChange: (value: string) => void;
}

export function TaskDialogCategoryChips({
  isCloudBrand,
  counts,
  statusCategory,
  onStatusCategoryChange,
}: TaskDialogCategoryChipsProps) {
  if (!counts) return null;

  return (
    <div
      className={cn(
        "flex flex-wrap items-center",
        isCloudBrand ? "gap-2 px-4" : "gap-1.5",
      )}
    >
      {CATEGORY_CHIPS.map((chip) => {
        const Icon = chip.icon;
        const isActive = statusCategory === chip.id;
        const count = counts[chip.id];

        return (
          <button
            key={chip.id}
            type="button"
            onClick={() =>
              onStatusCategoryChange(
                isActive ? ALL_TASK_STATUS_CATEGORIES : chip.id,
              )
            }
            className={cn(
              "inline-flex min-h-10 items-center gap-2 border text-sm transition-colors",
              isCloudBrand ? "px-4" : "px-3",
              isCloudBrand ? "rounded-full" : "rounded-lg",
              isCloudBrand
                ? isActive
                  ? "border-[var(--border-border-interactive)] bg-[#333333] text-foreground"
                  : "border-border-subtle-contextual bg-[#333333] text-layer-contextual-foreground hover:bg-[#333333] hover:text-foreground"
                : isActive
                  ? "border-border bg-task-dialog-oss-selected text-foreground"
                  : "border-border bg-muted hover:bg-badge hover:text-badge-foreground",
            )}
          >
            <Icon className={cn("size-4 shrink-0", chip.iconClassName)} />
            <span>{chip.label}</span>
            <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs font-medium tabular-nums">
              {count}
            </span>
          </button>
        );
      })}
    </div>
  );
}
