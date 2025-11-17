import { CheckIcon, ChevronsUpDownIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export type ModelOption = {
  value: string;
  label: string;
  default?: boolean;
  provider?: string;
};

export type GroupedModelOption = {
  group: string;
  options: ModelOption[];
  icon?: React.ReactNode;
};

export function ModelSelector({
  options,
  groupedOptions,
  value = "",
  onValueChange,
  icon,
  placeholder = "Select model...",
  searchPlaceholder = "Search model...",
  noOptionsPlaceholder = "No models available",
  custom = false,
  hasError = false,
}: {
  options?: ModelOption[];
  groupedOptions?: GroupedModelOption[];
  value: string;
  icon?: React.ReactNode;
  placeholder?: string;
  searchPlaceholder?: string;
  noOptionsPlaceholder?: string;
  custom?: boolean;
  onValueChange: (value: string, provider?: string) => void;
  hasError?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");

  // Flatten grouped options or use regular options
  const allOptions =
    groupedOptions?.flatMap((group) => group.options) || options || [];

  // Find the group icon for the selected value
  const selectedOptionGroup = groupedOptions?.find((group) =>
    group.options.some((opt) => opt.value === value),
  );
  const selectedIcon = selectedOptionGroup?.icon || icon;

  useEffect(() => {
    if (
      value &&
      value !== "" &&
      !allOptions.find((option) => option.value === value) &&
      !custom
    ) {
      onValueChange("");
    }
  }, [allOptions, value, custom, onValueChange]);

  return (
    <Popover open={open} onOpenChange={setOpen} modal={false}>
      <PopoverTrigger asChild>
        {/** biome-ignore lint/a11y/useSemanticElements: has to be a Button */}
        <Button
          variant="outline"
          role="combobox"
          disabled={allOptions.length === 0}
          aria-expanded={open}
          className={cn(
            "w-full gap-2 justify-between font-normal text-sm",
            hasError && "!border-destructive",
          )}
        >
          {value ? (
            <div className="flex items-center gap-2">
              {selectedIcon && <div className="w-4 h-4">{selectedIcon}</div>}
              {allOptions.find((framework) => framework.value === value)
                ?.label || value}
              {custom &&
                value &&
                !allOptions.find((framework) => framework.value === value) && (
                  <Badge variant="outline" className="text-xs">
                    CUSTOM
                  </Badge>
                )}
            </div>
          ) : allOptions.length === 0 ? (
            noOptionsPlaceholder
          ) : (
            placeholder
          )}
          <ChevronsUpDownIcon className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="p-0 w-[var(--radix-popover-trigger-width)]"
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <Command>
          <CommandInput
            placeholder={searchPlaceholder}
            value={searchValue}
            onValueChange={setSearchValue}
          />
          <CommandList
            className="max-h-[300px] overflow-y-auto"
            onWheel={(e) => e.stopPropagation()}
          >
            <CommandEmpty>{noOptionsPlaceholder}</CommandEmpty>
            {groupedOptions ? (
              groupedOptions.map((group) => (
                <CommandGroup
                  key={group.group}
                  heading={
                    <div className="flex items-center gap-2">
                      {group.icon && (
                        <div className="w-4 h-4">{group.icon}</div>
                      )}
                      <span>{group.group}</span>
                    </div>
                  }
                >
                  {group.options.map((option) => (
                    <CommandItem
                      key={option.value}
                      value={option.value}
                      onSelect={(currentValue) => {
                        if (currentValue !== value) {
                          onValueChange(currentValue, option.provider);
                        }
                        setOpen(false);
                      }}
                    >
                      <CheckIcon
                        className={cn(
                          "mr-2 h-4 w-4",
                          value === option.value ? "opacity-100" : "opacity-0",
                        )}
                      />
                      <div className="flex items-center gap-2">
                        {option.label}
                      </div>
                    </CommandItem>
                  ))}
                </CommandGroup>
              ))
            ) : (
              <CommandGroup>
                {allOptions.map((option) => (
                  <CommandItem
                    key={option.value}
                    value={option.value}
                    onSelect={(currentValue) => {
                      if (currentValue !== value) {
                        onValueChange(currentValue, option.provider);
                      }
                      setOpen(false);
                    }}
                  >
                    <CheckIcon
                      className={cn(
                        "mr-2 h-4 w-4",
                        value === option.value ? "opacity-100" : "opacity-0",
                      )}
                    />
                    <div className="flex items-center gap-2">
                      {option.label}
                    </div>
                  </CommandItem>
                ))}
                {custom &&
                  searchValue &&
                  !allOptions.find(
                    (option) => option.value === searchValue,
                  ) && (
                    <CommandItem
                      value={searchValue}
                      onSelect={(currentValue) => {
                        if (currentValue !== value) {
                          onValueChange(currentValue);
                        }
                        setOpen(false);
                      }}
                    >
                      <CheckIcon
                        className={cn(
                          "mr-2 h-4 w-4",
                          value === searchValue ? "opacity-100" : "opacity-0",
                        )}
                      />
                      <div className="flex items-center gap-2">
                        {searchValue}
                        <span className="text-xs text-foreground p-1 rounded-md bg-muted">
                          Custom
                        </span>
                      </div>
                    </CommandItem>
                  )}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
