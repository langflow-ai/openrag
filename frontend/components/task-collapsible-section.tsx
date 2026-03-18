"use client";

import { ChevronDown, ChevronUp } from "lucide-react";
import type { ReactNode } from "react";

interface TaskCollapsibleSectionProps<T> {
  title: string;
  items: T[];
  isOpen: boolean;
  onToggle: () => void;
  emptyText: string;
  renderItem: (item: T, index: number) => ReactNode;
  containerClassName?: string;
  contentClassName?: string;
}

export function TaskCollapsibleSection<T>({
  title,
  items,
  isOpen,
  onToggle,
  emptyText,
  renderItem,
  containerClassName = "",
  contentClassName = "",
}: TaskCollapsibleSectionProps<T>) {
  return (
    <div className={containerClassName}>
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between text-left hover:bg-muted/60 transition-colors !mt-0 p-4 border-t border-muted"
      >
        <h3 className="font-semibold text-sm flex items-center gap-2 text-muted-foreground">
          {title}
          <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted-foreground text-[10px] font-semibold text-background">
            {items.length}
          </span>
        </h3>
        {isOpen ? (
          <ChevronDown className="h-[14px] w-[14px] text-foreground" />
        ) : (
          <ChevronUp className="h-[14px] w-[14px] text-foreground" />
        )}
      </button>

      {isOpen && (
        <div className={contentClassName}>
          {items.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">{emptyText}</p>
          ) : (
            items.map((item, index) => renderItem(item, index))
          )}
        </div>
      )}
    </div>
  );
}
