"use client";

import { ChevronDown, Search } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { ALL_TASK_FILE_TYPES, formatTaskFileTypeLabel } from "@/lib/task-utils";
import { cn } from "@/lib/utils";

interface TaskDialogFiltersProps {
  isCloudBrand: boolean;
  search: string;
  onSearchChange: (value: string) => void;
  fileType: string;
  onFileTypeChange: (value: string) => void;
  fileTypes: string[];
  fileTypeLabel: string;
  searchDisabled: boolean;
  fileTypeDisabled: boolean;
}

function fileTypeItemClassName(selected: boolean) {
  return cn(
    "px-2",
    selected &&
      "bg-muted text-foreground focus:bg-muted data-[highlighted]:bg-muted",
  );
}

function FileTypeMenu({
  fileType,
  onFileTypeChange,
  fileTypes,
  allTypesLabel,
  trigger,
}: {
  fileType: string;
  onFileTypeChange: (value: string) => void;
  fileTypes: string[];
  allTypesLabel: string;
  trigger: ReactNode;
}) {
  const options = [
    { value: ALL_TASK_FILE_TYPES, label: allTypesLabel },
    ...fileTypes.map((type) => ({
      value: type,
      label: formatTaskFileTypeLabel(type),
    })),
  ];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[160px]">
        {options.map(({ value, label }) => (
          <DropdownMenuItem
            key={value}
            onSelect={() => onFileTypeChange(value)}
            className={fileTypeItemClassName(fileType === value)}
          >
            {label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function TaskDialogFilters({
  isCloudBrand,
  search,
  onSearchChange,
  fileType,
  onFileTypeChange,
  fileTypes,
  fileTypeLabel,
  searchDisabled,
  fileTypeDisabled,
}: TaskDialogFiltersProps) {
  const allTypesLabel = isCloudBrand ? "All categories" : "All file types";

  if (isCloudBrand) {
    return (
      <div className="flex min-h-10 items-stretch border-b border-border [&_input]:min-h-10">
        <div className="min-w-0 flex-1 border-r border-border-subtle-contextual bg-layer-contextual">
          <Input
            type="search"
            autoComplete="off"
            placeholder="Search files..."
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            disabled={searchDisabled}
            icon={<Search className="h-4 w-4" aria-hidden />}
            inputClassName="h-10 min-w-0 !rounded-none !border-0 bg-layer-contextual text-layer-contextual-foreground placeholder:text-muted-foreground focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          />
        </div>
        <FileTypeMenu
          fileType={fileType}
          onFileTypeChange={onFileTypeChange}
          fileTypes={fileTypes}
          allTypesLabel={allTypesLabel}
          trigger={
            <button
              type="button"
              disabled={fileTypeDisabled}
              className="inline-flex min-h-10 w-[160px] shrink-0 items-center justify-between gap-2 px-4 text-sm text-muted-foreground transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
            >
              <span className="truncate">{fileTypeLabel}</span>
              <ChevronDown className="h-4 w-4 shrink-0 opacity-70" />
            </button>
          }
        />
      </div>
    );
  }

  return (
    <div className="flex min-h-10 items-center gap-2">
      <div className="relative min-w-0 flex-1">
        <Input
          type="search"
          autoComplete="off"
          placeholder="Search connectors..."
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          disabled={searchDisabled}
          icon={<Search className="h-4 w-4" aria-hidden />}
          inputClassName="h-10 rounded-md !bg-canvas"
        />
      </div>
      <FileTypeMenu
        fileType={fileType}
        onFileTypeChange={onFileTypeChange}
        fileTypes={fileTypes}
        allTypesLabel={allTypesLabel}
        trigger={
          <Button
            type="button"
            variant="outline"
            disabled={fileTypeDisabled}
            className="min-h-10 h-10 w-[160px] shrink-0 justify-between font-normal"
          >
            <span className="truncate">{fileTypeLabel}</span>
            <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        }
      />
    </div>
  );
}
