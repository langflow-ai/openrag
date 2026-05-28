"use client";

import { ChevronDown, ChevronUp, Search } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { ALL_TASK_FILE_TYPES, formatTaskFileTypeLabel } from "@/lib/task-utils";
import { cn } from "@/lib/utils";

interface TaskDialogFiltersProps {
  search: string;
  onSearchChange: (value: string) => void;
  fileType: string;
  onFileTypeChange: (value: string) => void;
  fileTypes: string[];
  fileTypeLabel: string;
  searchDisabled: boolean;
  fileTypeDisabled: boolean;
}

function FileTypeMenu({
  fileType,
  onFileTypeChange,
  fileTypes,
  allTypesLabel,
  fileTypeLabel,
  disabled,
}: {
  fileType: string;
  onFileTypeChange: (value: string) => void;
  fileTypes: string[];
  allTypesLabel: string;
  fileTypeLabel: string;
  disabled: boolean;
}) {
  const isCloudBrand = useIsCloudBrand();
  const [open, setOpen] = useState(false);
  const options = [
    { value: ALL_TASK_FILE_TYPES, label: allTypesLabel },
    ...fileTypes.map((type) => ({
      value: type,
      label: formatTaskFileTypeLabel(type),
    })),
  ];

  const ChevronIcon = open ? ChevronUp : ChevronDown;
  const triggerContent = (
    <>
      <span className="truncate">{fileTypeLabel}</span>
      <ChevronIcon
        className={cn(
          "h-4 w-4 shrink-0",
          isCloudBrand ? "opacity-70" : "ml-2 opacity-50",
        )}
        aria-hidden
      />
    </>
  );

  return (
    <DropdownMenu modal={false} open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        {isCloudBrand ? (
          <button
            type="button"
            disabled={disabled}
            className="inline-flex min-h-10 w-task-dialog-file-type shrink-0 items-center justify-between gap-2 bg-layer-contextual px-4 text-sm text-muted-foreground transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
          >
            {triggerContent}
          </button>
        ) : (
          <Button
            type="button"
            variant="outline"
            disabled={disabled}
            className="min-h-10 h-10 w-task-dialog-file-type shrink-0 justify-between font-normal"
          >
            {triggerContent}
          </Button>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className={cn(
          "z-task-dialog-menu w-task-dialog-file-type",
          isCloudBrand &&
            "border-border-subtle-contextual bg-layer-contextual text-layer-contextual-foreground",
        )}
        onCloseAutoFocus={(event) => event.preventDefault()}
      >
        {options.map(({ value, label }) => (
          <DropdownMenuItem
            key={value}
            onSelect={() => onFileTypeChange(value)}
            className={cn(
              "px-2",
              isCloudBrand &&
                "bg-layer-contextual text-layer-contextual-foreground hover:bg-muted focus:bg-muted data-[highlighted]:bg-muted",
              fileType === value &&
                "bg-muted text-foreground focus:bg-muted data-[highlighted]:bg-muted",
            )}
          >
            {label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function TaskDialogSearchField({
  search,
  onSearchChange,
  disabled,
}: {
  search: string;
  onSearchChange: (value: string) => void;
  disabled: boolean;
}) {
  const isCloudBrand = useIsCloudBrand();
  const input = (
    <Input
      type="search"
      autoComplete="off"
      placeholder="Search files..."
      value={search}
      onChange={(e) => onSearchChange(e.target.value)}
      disabled={disabled}
      icon={<Search className="h-4 w-4" aria-hidden />}
      inputClassName={
        isCloudBrand
          ? "h-10 min-w-0 !rounded-none !border-0 bg-layer-contextual text-layer-contextual-foreground placeholder:text-muted-foreground focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          : "h-10 rounded-md !bg-canvas"
      }
    />
  );

  return (
    <div
      className={
        isCloudBrand
          ? "min-w-0 flex-1 border-r border-border-subtle-contextual bg-layer-contextual"
          : "relative min-w-0 flex-1"
      }
    >
      {input}
    </div>
  );
}

export function TaskDialogFilters({
  search,
  onSearchChange,
  fileType,
  onFileTypeChange,
  fileTypes,
  fileTypeLabel,
  searchDisabled,
  fileTypeDisabled,
}: TaskDialogFiltersProps) {
  const isCloudBrand = useIsCloudBrand();
  const fileTypeMenuProps = {
    fileType,
    onFileTypeChange,
    fileTypes,
    allTypesLabel: isCloudBrand ? "All categories" : "All file types",
    fileTypeLabel,
    disabled: fileTypeDisabled,
  };

  return (
    <div
      className={cn(
        "flex min-h-10",
        isCloudBrand
          ? "items-stretch border-y border-border bg-layer-contextual [&_input]:min-h-10"
          : "items-center gap-2",
      )}
    >
      <TaskDialogSearchField
        search={search}
        onSearchChange={onSearchChange}
        disabled={searchDisabled}
      />
      <FileTypeMenu {...fileTypeMenuProps} />
    </div>
  );
}
