"use client";

import { Check, ChevronDown } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

interface Option {
  value: string;
  label: string;
  count?: number;
  /** Renders the row unselectable. Selecting it is a no-op. */
  disabled?: boolean;
  /** Short reason shown beside a disabled row, e.g. why it is unavailable. */
  hint?: string;
}

interface MultiSelectProps {
  options: Option[];
  value: string[];
  onValueChange: (value: string[]) => void;
  placeholder?: string;
  className?: string;
  maxSelection?: number;
  searchPlaceholder?: string;
  showAllOption?: boolean;
  allOptionLabel?: string;
  disabled?: boolean;
  /**
   * Name the selected options on the trigger while at most this many are
   * chosen, instead of showing a bare count. 0 always shows the count.
   */
  inlineLabelLimit?: number;
}

export function MultiSelect({
  options,
  value,
  onValueChange,
  placeholder = "Select items...",
  className,
  maxSelection,
  searchPlaceholder = "Search options...",
  showAllOption = true,
  allOptionLabel = "All",
  disabled = false,
  inlineLabelLimit = 0,
}: MultiSelectProps) {
  const [open, setOpen] = React.useState(false);
  const [searchValue, setSearchValue] = React.useState("");
  const listboxId = React.useId();

  // Normalize value to empty array if undefined/null to prevent crashes
  const safeValue = value ?? [];

  const isAllSelected = safeValue.includes("*");

  const filteredOptions = options.filter((option) =>
    option.label.toLowerCase().includes(searchValue.toLowerCase()),
  );

  const handleSelect = (optionValue: string) => {
    if (options.find((option) => option.value === optionValue)?.disabled) {
      return;
    }
    if (optionValue === "*") {
      // Toggle "All" selection
      if (isAllSelected) {
        onValueChange([]);
      } else {
        onValueChange(["*"]);
      }
    } else {
      let newValue: string[];
      if (safeValue.includes(optionValue)) {
        // Remove the item
        newValue = safeValue.filter((v) => v !== optionValue && v !== "*");
      } else {
        // Add the item and remove "All" if present
        newValue = [...safeValue.filter((v) => v !== "*"), optionValue];

        // Check max selection limit
        if (maxSelection && newValue.length > maxSelection) {
          return;
        }
      }
      onValueChange(newValue);
    }
  };

  const getDisplayText = () => {
    if (isAllSelected) {
      return allOptionLabel;
    }

    if (safeValue.length === 0) {
      return placeholder;
    }

    // A short selection reads better named than counted: "English, Japanese"
    // says what OCR will run, "2 languages" makes you open the dropdown.
    if (safeValue.length <= inlineLabelLimit) {
      return safeValue
        .map(
          (selected) =>
            options.find((option) => option.value === selected)?.label ??
            selected,
        )
        .join(", ");
    }

    // Extract the noun from placeholder (e.g., "Select data sources..." -> "data sources")
    const noun = placeholder
      .toLowerCase()
      .replace("select ", "")
      .replace("...", "");
    return `${safeValue.length} ${noun}`;
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          disabled={disabled}
          aria-expanded={open}
          aria-controls={listboxId}
          className={cn("w-full justify-between h-8 py-0 text-left", className)}
        >
          <span className="text-foreground text-sm">{getDisplayText()}</span>
          <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="p-0"
        align="start"
        style={{ width: "var(--radix-popover-trigger-width)" }}
      >
        <Command shouldFilter={false}>
          <CommandInput
            placeholder={searchPlaceholder}
            value={searchValue}
            onValueChange={setSearchValue}
          />
          <CommandEmpty>No items found.</CommandEmpty>
          <CommandGroup id={listboxId}>
            <ScrollArea className="max-h-64">
              {showAllOption && (
                <CommandItem
                  key="all"
                  onSelect={() => handleSelect("*")}
                  className="cursor-pointer"
                >
                  <span className="flex-1 truncate min-w-0">
                    {allOptionLabel}
                  </span>
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4",
                      isAllSelected ? "opacity-100" : "opacity-0",
                    )}
                  />
                </CommandItem>
              )}
              {filteredOptions.map((option) => (
                <CommandItem
                  key={option.value}
                  onSelect={() => handleSelect(option.value)}
                  disabled={option.disabled}
                  aria-disabled={option.disabled}
                  className={cn(
                    option.disabled
                      ? "cursor-not-allowed opacity-50"
                      : "cursor-pointer",
                  )}
                >
                  <span className="flex-1 truncate min-w-0">
                    {option.label}
                  </span>
                  {option.hint && (
                    <span className="text-xs text-muted-foreground ml-2 shrink-0">
                      {option.hint}
                    </span>
                  )}
                  {option.count !== undefined && (
                    <span className="text-xs text-muted-foreground bg-muted/50 px-1.5 py-0.5 rounded ml-2">
                      {option.count}
                    </span>
                  )}
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4",
                      safeValue.includes(option.value)
                        ? "opacity-100"
                        : "opacity-0",
                    )}
                  />
                </CommandItem>
              ))}
            </ScrollArea>
          </CommandGroup>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
