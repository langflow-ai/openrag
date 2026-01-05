"use client";

import * as React from "react";
import { ChevronDown, Check } from "lucide-react";
import { cn } from "@/lib/utils";
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

interface Option {
  value: string;
  label: string;
  count?: number;
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
}: MultiSelectProps) {
  const [open, setOpen] = React.useState(false);
  const [searchValue, setSearchValue] = React.useState("");

  // Normalize value to empty array if undefined/null to prevent crashes
  const safeValue = value ?? [];

  const isAllSelected = safeValue.includes("*");

  const filteredOptions = options.filter((option) =>
    option.label.toLowerCase().includes(searchValue.toLowerCase()),
  );

  const handleSelect = (optionValue: string) => {
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
          aria-expanded={open}
          className={cn("w-full justify-between h-8 py-0 text-left", className)}
        >
          <span className="text-foreground text-sm">{getDisplayText()}</span>
          <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="p-0" align="start">
        <Command>
          <CommandInput
            placeholder={searchPlaceholder}
            value={searchValue}
            onValueChange={setSearchValue}
          />
          <CommandEmpty>No items found.</CommandEmpty>
          <CommandGroup>
            <ScrollArea className="max-h-64">
              {showAllOption && (
                <CommandItem
                  key="all"
                  onSelect={() => handleSelect("*")}
                  className="cursor-pointer"
                >
                  <span className="flex-1">{allOptionLabel}</span>
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
                  className="cursor-pointer"
                >
                  <span className="flex-1">{option.label}</span>
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
