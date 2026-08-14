"use client";

import { CheckIcon, ChevronsUpDownIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button, type ButtonProps } from "@/components/ui/button";
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

export interface ModelSelectorProps extends ButtonProps {
  options?: ModelOption[];
  groupedOptions?: GroupedModelOption[];
  value: string;
  icon?: React.ReactNode;
  /**
   * The provider the currently selected `value` actually belongs to (e.g.
   * `settings.agent.llm_provider`). Disambiguates the selected-icon lookup
   * when the same model name exists under more than one provider's group
   * (e.g. "gpt-5-nano" as both an OpenAI model and an Azure AI Foundry
   * deployment name) — without it, the first group containing a matching
   * value wins, which can show the wrong provider's logo.
   */
  selectedProvider?: string;
  placeholder?: string;
  searchPlaceholder?: string;
  noOptionsPlaceholder?: string;
  custom?: boolean;
  onValueChange: (value: string, provider?: string) => void;
  hasError?: boolean;
  defaultOpen?: boolean;
}

export function ModelSelector({
  options,
  groupedOptions,
  value = "",
  onValueChange,
  icon,
  selectedProvider,
  placeholder = "Select model...",
  searchPlaceholder = "Search model...",
  noOptionsPlaceholder = "No models available",
  custom = false,
  hasError = false,
  defaultOpen = false,
  className,
  disabled,
  variant = "outline",
  ...props
}: ModelSelectorProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [searchValue, setSearchValue] = useState("");

  // Flatten grouped options or use regular options
  const allOptions =
    groupedOptions?.flatMap((group) => group.options) || options || [];

  // Find the group icon for the selected value. The same model name can
  // exist under more than one provider's group (e.g. "gpt-5-nano" as both an
  // OpenAI model and an Azure AI Foundry deployment name) — when the caller
  // tells us which provider is actually selected, prefer the group whose
  // option matches on value AND provider so the icon doesn't just default to
  // whichever group happens to list that value first.
  const selectedOptionGroup =
    (selectedProvider &&
      groupedOptions?.find((group) =>
        group.options.some(
          (opt) => opt.value === value && opt.provider === selectedProvider,
        ),
      )) ||
    groupedOptions?.find((group) =>
      group.options.some((opt) => opt.value === value),
    );
  const selectedIcon = selectedOptionGroup?.icon || icon;

  useEffect(() => {
    if (
      allOptions.length > 0 &&
      value &&
      value !== "" &&
      !allOptions.some((option) => option.value === value) &&
      !custom
    ) {
      onValueChange("");
    }
  }, [allOptions, value, custom, onValueChange]);

  // Update open state when defaultOpen changes
  useEffect(() => {
    if (defaultOpen) {
      setOpen(true);
    }
  }, [defaultOpen]);

  return (
    <Popover open={open} onOpenChange={setOpen} modal={false}>
      <PopoverTrigger asChild>
        <Button
          variant={variant}
          role="combobox"
          disabled={disabled || allOptions.length === 0}
          aria-expanded={open}
          className={cn(
            "w-full gap-2 justify-between font-normal text-sm",
            hasError && "!border-destructive",
            className,
          )}
          {...props}
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
                  {group.options.length === 0 ? (
                    <CommandItem
                      disabled
                      className="text-muted-foreground ml-6"
                    >
                      No models available
                    </CommandItem>
                  ) : (
                    group.options.map((option) => {
                      const isSelected =
                        value === option.value &&
                        (!selectedProvider ||
                          !option.provider ||
                          selectedProvider === option.provider);
                      return (
                        <CommandItem
                          key={`${option.provider || group.group}:${option.value}`}
                          value={`${option.provider || group.group}:${option.value}`}
                          data-testid={`model-option-${option.value}`}
                          onSelect={() => {
                            if (
                              option.value !== value ||
                              (option.provider &&
                                option.provider !== selectedProvider)
                            ) {
                              onValueChange(option.value, option.provider);
                            }
                            setOpen(false);
                          }}
                        >
                          <CheckIcon
                            className={cn(
                              "mr-2 h-4 w-4",
                              isSelected ? "opacity-100" : "opacity-0",
                            )}
                          />
                          <div className="flex items-center gap-2">
                            {option.label}
                          </div>
                        </CommandItem>
                      );
                    })
                  )}
                </CommandGroup>
              ))
            ) : (
              <CommandGroup>
                {allOptions.map((option) => {
                  const isSelected =
                    value === option.value &&
                    (!selectedProvider ||
                      !option.provider ||
                      selectedProvider === option.provider);
                  return (
                    <CommandItem
                      key={`${option.provider || "default"}:${option.value}`}
                      value={`${option.provider || "default"}:${option.value}`}
                      data-testid={`model-option-${option.value}`}
                      onSelect={() => {
                        if (
                          option.value !== value ||
                          (option.provider &&
                            option.provider !== selectedProvider)
                        ) {
                          onValueChange(option.value, option.provider);
                        }
                        setOpen(false);
                      }}
                    >
                      <CheckIcon
                        className={cn(
                          "mr-2 h-4 w-4",
                          isSelected ? "opacity-100" : "opacity-0",
                        )}
                      />
                      <div className="flex items-center gap-2">
                        {option.label}
                      </div>
                    </CommandItem>
                  );
                })}
                {custom &&
                  searchValue &&
                  !allOptions.find(
                    (option) => option.value === searchValue,
                  ) && (
                    <CommandItem
                      value={searchValue}
                      data-testid={`model-custom-option-${searchValue}`}
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
