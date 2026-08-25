"use client";

import { CheckIcon, ChevronsUpDownIcon } from "lucide-react";
import { useDeferredValue, useEffect, useId, useMemo, useState } from "react";
import type { CatalogModel } from "@/app/settings/_helpers/catalog-models";
import { MODELS_PER_PROVIDER } from "@/app/settings/_helpers/model-info";
import { Badge } from "@/components/ui/badge";
import { Button, type ButtonProps } from "@/components/ui/button";
import {
  Command,
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
import { CapabilityStrip } from "./model-features";

export type ModelOption = {
  value: string;
  label: string;
  default?: boolean;
  provider?: string;
  model?: CatalogModel;
  icon?: React.ReactNode;
};

export type GroupedModelOption = {
  group: string;
  /** Provider key for custom entries typed under this group. */
  provider?: string;
  options: ModelOption[];
  icon?: React.ReactNode;
};

export interface ModelSelectorProps extends ButtonProps {
  options?: ModelOption[];
  groupedOptions?: GroupedModelOption[];
  value: string;
  /** Disambiguates the same model id hosted by more than one vendor. */
  selectedProvider?: string;
  icon?: React.ReactNode;
  placeholder?: string;
  searchPlaceholder?: string;
  noOptionsPlaceholder?: string;
  custom?: boolean;
  onValueChange: (value: string, provider?: string) => void;
  hasError?: boolean;
  defaultOpen?: boolean;
}

function optionProvider(
  option: ModelOption,
  group?: GroupedModelOption,
): string | undefined {
  return option.provider ?? group?.provider;
}

function isSelectedRow(
  option: ModelOption,
  value: string,
  selectedProvider?: string,
  group?: GroupedModelOption,
): boolean {
  if (option.value !== value) {
    return false;
  }
  if (!selectedProvider) {
    return true;
  }
  const provider = optionProvider(option, group);
  return !provider || provider === selectedProvider;
}

export function ModelSelector({
  options,
  groupedOptions,
  value = "",
  selectedProvider,
  onValueChange,
  icon,
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
  const [prevDefaultOpen, setPrevDefaultOpen] = useState(defaultOpen);
  if (defaultOpen !== prevDefaultOpen) {
    setPrevDefaultOpen(defaultOpen);
    if (defaultOpen) {
      setOpen(true);
    }
  }

  const [searchValue, setSearchValue] = useState("");
  // The option filter runs on the trimmed, lowercased search text, so the
  // custom entry has to use the trimmed text too — otherwise typing trailing
  // whitespace both defeats the duplicate check and stores a model id with
  // whitespace in it.
  const customValue = searchValue.trim();
  const deferredSearch = useDeferredValue(customValue.toLowerCase());
  const listboxId = useId();

  // Flatten grouped options or use regular options
  const allOptions =
    groupedOptions?.flatMap((group) => group.options) || options || [];
  const allowCustomEntry = !!custom;

  const selectedOptionGroup = groupedOptions?.find((group) =>
    selectedProvider
      ? group.provider === selectedProvider
      : group.options.some((opt) => opt.value === value),
  );
  const selectedOption = allOptions.find((option) =>
    isSelectedRow(option, value, selectedProvider, selectedOptionGroup),
  );
  const selectedIcon =
    selectedOption?.icon || selectedOptionGroup?.icon || icon;

  const visibleGroups = useMemo(() => {
    if (!groupedOptions) return undefined;
    const matched = groupedOptions.flatMap((group) => {
      const providerMatches = group.group
        .toLowerCase()
        .includes(deferredSearch);
      const options = deferredSearch
        ? group.options.filter(
            (option) =>
              providerMatches ||
              option.label.toLowerCase().includes(deferredSearch),
          )
        : group.options.slice(0, MODELS_PER_PROVIDER);
      if (deferredSearch && options.length === 0) return [];
      return [{ ...group, options }];
    });
    return matched.slice(0, 40);
  }, [deferredSearch, groupedOptions]);
  const visibleOptions = useMemo(() => {
    if (groupedOptions) return [];
    const source = options ?? [];
    if (!deferredSearch) return source.slice(0, 40);
    return source
      .filter((option) => option.label.toLowerCase().includes(deferredSearch))
      .slice(0, 100);
  }, [deferredSearch, groupedOptions, options]);

  // `shouldFilter={false}` means cmdk's own item count no longer reflects the
  // manual filtering above, so `CommandEmpty` cannot be trusted to appear.
  // Decide the empty state from the collections that actually render.
  const showCustomEntry = allowCustomEntry && !!customValue;
  // Grouped custom rows live inside a group, so a search that filters every
  // group away also takes the custom entry with it. Offer it on its own so a
  // model that is not in the catalogue can still be typed.
  const showUngroupedCustomEntry =
    showCustomEntry && !!groupedOptions && (visibleGroups?.length ?? 0) === 0;
  const showFlatCustomEntry =
    showCustomEntry &&
    !groupedOptions &&
    !allOptions.some((option) => option.value === customValue);
  const hasVisibleRows = groupedOptions
    ? (visibleGroups?.length ?? 0) > 0 || showUngroupedCustomEntry
    : visibleOptions.length > 0 || showFlatCustomEntry;

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

  return (
    <Popover open={open} onOpenChange={setOpen} modal={false}>
      <PopoverTrigger asChild>
        <Button
          variant={variant}
          role="combobox"
          disabled={disabled || (allOptions.length === 0 && !allowCustomEntry)}
          aria-expanded={open}
          aria-controls={listboxId}
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
              {selectedOption?.label || value}
              {custom &&
                value &&
                !allOptions.find((framework) => framework.value === value) && (
                  <Badge variant="outline" className="text-xs">
                    CUSTOM
                  </Badge>
                )}
            </div>
          ) : allOptions.length === 0 && !allowCustomEntry ? (
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
        <Command shouldFilter={false}>
          <CommandInput
            placeholder={searchPlaceholder}
            value={searchValue}
            onValueChange={setSearchValue}
          />
          <CommandList
            id={listboxId}
            className="max-h-[300px] overflow-y-auto"
            onWheel={(e) => e.stopPropagation()}
          >
            {!hasVisibleRows && (
              <div className="py-6 text-center text-sm">
                {noOptionsPlaceholder}
              </div>
            )}
            {groupedOptions ? (
              <>
                {visibleGroups?.map((group) => {
                  const groupProvider =
                    group.provider ?? group.options[0]?.provider;
                  const showCustom =
                    showCustomEntry &&
                    !group.options.some(
                      (option) => option.value === customValue,
                    );
                  return (
                    <CommandGroup
                      key={group.group}
                      data-testid={
                        groupProvider
                          ? `model-group-${groupProvider}`
                          : undefined
                      }
                      heading={
                        <div className="flex items-center gap-2">
                          {group.icon && (
                            <div className="w-4 h-4">{group.icon}</div>
                          )}
                          <span>{group.group}</span>
                        </div>
                      }
                    >
                      {group.options.length === 0 && !showCustom ? (
                        <CommandItem
                          disabled
                          className="text-muted-foreground ml-6"
                        >
                          No models available. Search to enter a custom model.
                        </CommandItem>
                      ) : (
                        group.options.map((option) => {
                          const itemProvider = option.provider ?? groupProvider;
                          const itemKey = itemProvider
                            ? `${itemProvider}:${option.value}`
                            : option.value;
                          return (
                            <CommandItem
                              key={itemKey}
                              value={itemKey}
                              data-testid={`model-option-${option.value}`}
                              onSelect={() => {
                                if (
                                  option.value !== value ||
                                  itemProvider !== selectedProvider
                                ) {
                                  onValueChange(option.value, itemProvider);
                                }
                                setOpen(false);
                              }}
                            >
                              <CheckIcon
                                className={cn(
                                  "mr-2 h-4 w-4",
                                  isSelectedRow(
                                    option,
                                    value,
                                    selectedProvider,
                                    group,
                                  )
                                    ? "opacity-100"
                                    : "opacity-0",
                                )}
                              />
                              <div className="flex items-center gap-2">
                                {option.icon && (
                                  <span className="h-4 w-4">{option.icon}</span>
                                )}
                                {option.label}
                              </div>
                              {option.model && (
                                <CapabilityStrip model={option.model} />
                              )}
                            </CommandItem>
                          );
                        })
                      )}
                      {!deferredSearch &&
                        (groupedOptions.find(
                          (entry) => entry.group === group.group,
                        )?.options.length ?? 0) > MODELS_PER_PROVIDER && (
                          <CommandItem disabled className="text-xs">
                            Search to view{" "}
                            {(groupedOptions.find(
                              (entry) => entry.group === group.group,
                            )?.options.length ?? 0) - MODELS_PER_PROVIDER}{" "}
                            more models
                          </CommandItem>
                        )}
                      {showCustom && (
                        <CommandItem
                          value={`${group.group}-${customValue}`}
                          data-testid={`model-custom-option-${customValue}`}
                          onSelect={() => {
                            if (
                              customValue !== value ||
                              groupProvider !== selectedProvider
                            ) {
                              onValueChange(customValue, groupProvider);
                            }
                            setOpen(false);
                          }}
                        >
                          <CheckIcon
                            className={cn(
                              "mr-2 h-4 w-4",
                              value === customValue &&
                                (!selectedProvider ||
                                  selectedProvider === groupProvider)
                                ? "opacity-100"
                                : "opacity-0",
                            )}
                          />
                          <div className="flex items-center gap-2">
                            {customValue}
                            <span className="text-xs text-foreground p-1 rounded-md bg-muted">
                              Custom
                            </span>
                          </div>
                        </CommandItem>
                      )}
                    </CommandGroup>
                  );
                })}
                {showUngroupedCustomEntry && (
                  <CommandGroup>
                    <CommandItem
                      value={customValue}
                      data-testid={`model-custom-option-${customValue}`}
                      onSelect={() => {
                        if (customValue !== value) {
                          onValueChange(customValue, selectedProvider);
                        }
                        setOpen(false);
                      }}
                    >
                      <CheckIcon
                        className={cn(
                          "mr-2 h-4 w-4",
                          value === customValue ? "opacity-100" : "opacity-0",
                        )}
                      />
                      <div className="flex items-center gap-2">
                        {customValue}
                        <span className="text-xs text-foreground p-1 rounded-md bg-muted">
                          Custom
                        </span>
                      </div>
                    </CommandItem>
                  </CommandGroup>
                )}
              </>
            ) : (
              <CommandGroup>
                {visibleOptions.map((option) => (
                  <CommandItem
                    key={option.value}
                    value={option.value}
                    data-testid={`model-option-${option.value}`}
                    onSelect={() => {
                      if (
                        option.value !== value ||
                        option.provider !== selectedProvider
                      ) {
                        onValueChange(option.value, option.provider);
                      }
                      setOpen(false);
                    }}
                  >
                    <CheckIcon
                      className={cn(
                        "mr-2 h-4 w-4",
                        isSelectedRow(option, value, selectedProvider)
                          ? "opacity-100"
                          : "opacity-0",
                      )}
                    />
                    <div className="flex items-center gap-2">
                      {option.icon && (
                        <span className="h-4 w-4">{option.icon}</span>
                      )}
                      {option.label}
                    </div>
                  </CommandItem>
                ))}
                {showFlatCustomEntry && (
                  <CommandItem
                    value={customValue}
                    data-testid={`model-custom-option-${customValue}`}
                    onSelect={() => {
                      if (customValue !== value) {
                        onValueChange(customValue);
                      }
                      setOpen(false);
                    }}
                  >
                    <CheckIcon
                      className={cn(
                        "mr-2 h-4 w-4",
                        value === customValue ? "opacity-100" : "opacity-0",
                      )}
                    />
                    <div className="flex items-center gap-2">
                      {customValue}
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
