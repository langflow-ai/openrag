"use client";

import { CheckIcon, ChevronsUpDownIcon } from "lucide-react";
import { useDeferredValue, useEffect, useId, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { CapabilityStrip } from "./capability-strip";
import { MODELS_PER_PROVIDER } from "./model-info";
import type {
  GroupedModelOption,
  ModelOption,
  ModelSelectorProps,
} from "./types";

// Re-exported so existing `from "@/components/models/model-selector"` imports
// keep working; the definitions themselves live in `./types` now.
export type {
  GroupedModelOption,
  ModelOption,
  ModelSelectorProps,
} from "./types";

function optionProvider(
  option: ModelOption,
  group?: GroupedModelOption,
): string | undefined {
  return option.provider ?? group?.provider;
}

/** How close a retirement has to be before the model drops out of the list. */
const RETIRING_SOON_DAYS = 90;

/**
 * A model close enough to retirement to be worth hiding by default.
 *
 * Not simply "has a deprecation_date": providers use that field very
 * differently. Anthropic stamps one on *every* model at launch, roughly a year
 * out, so hiding on presence alone would leave 2 of its 17 models on screen.
 * OpenAI leaves current models undated and sunsets a whole legacy generation
 * on one shared date. A window reads correctly for both — it hides OpenAI's
 * gpt-3.5 family and Anthropic's 4-5 generation, and nothing at all for
 * providers that publish no dates.
 *
 * The backend already drops models whose date has passed, so anything here is
 * still callable — hidden, never taken away.
 */
function isRetiringSoon(option: ModelOption): boolean {
  const date = option.model?.deprecation_date;
  if (!date) return false;
  const retires = Date.parse(date);
  if (Number.isNaN(retires)) return false;
  return retires <= Date.now() + RETIRING_SOON_DAYS * 86_400_000;
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
  searchPlaceholder,
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

  // A selector that accepts a typed model has to say so: the box is the only
  // way to reach a deployment name the catalogue cannot know. Selectors that
  // only pick from a fixed list (the watsonx endpoint picker) keep the plain
  // label, and any caller passing its own copy still wins.
  const searchBoxPlaceholder =
    searchPlaceholder ??
    (custom ? "Search or type a model name" : "Search model...");

  const [searchValue, setSearchValue] = useState("");
  // The option filter runs on the trimmed, lowercased search text, so the
  // custom entry has to use the trimmed text too — otherwise typing trailing
  // whitespace both defeats the duplicate check and stores a model id with
  // whitespace in it.
  const customValue = searchValue.trim();
  const deferredSearch = useDeferredValue(customValue.toLowerCase());
  const listboxId = useId();
  // Groups the user chose to expand past MODELS_PER_PROVIDER.
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
    () => new Set(),
  );
  const toggleGroup = (group: string) =>
    setExpandedGroups((previous) => {
      const next = new Set(previous);
      if (!next.delete(group)) next.add(group);
      return next;
    });
  // Groups the user chose to see retiring models in.
  const [deprecatedGroups, setDeprecatedGroups] = useState<Set<string>>(
    () => new Set(),
  );
  const toggleDeprecated = (group: string) =>
    setDeprecatedGroups((previous) => {
      const next = new Set(previous);
      if (!next.delete(group)) next.add(group);
      return next;
    });

  // Flatten grouped options or use regular options. Memoized so the effect
  // below (which depends on allOptions) doesn't re-run on every render.
  const allOptions = useMemo(
    () => groupedOptions?.flatMap((group) => group.options) || options || [],
    [groupedOptions, options],
  );
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
      const searched = deferredSearch
        ? group.options.filter(
            (option) =>
              providerMatches ||
              option.label.toLowerCase().includes(deferredSearch),
          )
        : group.options;
      // Retiring models are hidden until asked for, but never the one already
      // selected — taking the current choice off the list would make the
      // selector look broken to whoever set it.
      const deprecatedCount = searched.filter(isRetiringSoon).length;
      const matches = deprecatedGroups.has(group.group)
        ? searched
        : searched.filter(
            (option) =>
              !isRetiringSoon(option) ||
              isSelectedRow(option, value, selectedProvider, group),
          );
      if (deferredSearch && matches.length === 0 && deprecatedCount === 0) {
        return [];
      }
      // Collapsed groups show a preview; the trailing row expands them. The cap
      // applies while searching too, so without that row a search would drop
      // matches with nothing on screen to say so.
      const options = expandedGroups.has(group.group)
        ? matches
        : matches.slice(0, MODELS_PER_PROVIDER);
      return [
        { ...group, options, matchCount: matches.length, deprecatedCount },
      ];
    });
    return matched.slice(0, 40);
  }, [
    deferredSearch,
    groupedOptions,
    expandedGroups,
    deprecatedGroups,
    value,
    selectedProvider,
  ]);
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
            // Located by test id, not by placeholder: the copy changes with
            // `custom` and is the sort of thing that gets reworded.
            data-testid="model-search-input"
            placeholder={searchBoxPlaceholder}
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
                              // The capability icons and the context-length
                              // badge below are descendants of this option, so
                              // without an explicit label the accessible name
                              // becomes "<model> Tools: supported ... 128K".
                              // Name the option after the model it selects.
                              aria-label={option.label}
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
                      {group.matchCount > MODELS_PER_PROVIDER && (
                        <CommandItem
                          value={`__toggle-${group.group}`}
                          aria-label={
                            group.options.length < group.matchCount
                              ? `Show ${group.matchCount - group.options.length} more ${group.group} models`
                              : `Show fewer ${group.group} models`
                          }
                          data-testid={
                            groupProvider
                              ? `model-group-toggle-${groupProvider}`
                              : undefined
                          }
                          className="text-xs text-muted-foreground"
                          onSelect={() => toggleGroup(group.group)}
                        >
                          {group.options.length < group.matchCount
                            ? `Show ${group.matchCount - group.options.length} more`
                            : "Show fewer"}
                        </CommandItem>
                      )}
                      {group.deprecatedCount > 0 && (
                        <CommandItem
                          value={`__deprecated-${group.group}`}
                          aria-label={
                            deprecatedGroups.has(group.group)
                              ? `Hide retiring ${group.group} models`
                              : `Show ${group.deprecatedCount} retiring ${group.group} models`
                          }
                          data-testid={
                            groupProvider
                              ? `model-group-deprecated-${groupProvider}`
                              : undefined
                          }
                          className="text-xs text-muted-foreground"
                          onSelect={() => toggleDeprecated(group.group)}
                        >
                          {deprecatedGroups.has(group.group)
                            ? "Hide retiring models"
                            : `Show ${group.deprecatedCount} retiring`}
                        </CommandItem>
                      )}
                      {showCustom && (
                        <CommandItem
                          value={`${group.group}-${customValue}`}
                          aria-label={customValue}
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
                            {/* "Use" rather than the bare name: the row sits
                                among search results, and without a verb it
                                reads as one more model that already exists
                                rather than the thing that adds yours. */}
                            <span>Use</span>
                            {/* The provider tag is shown, never typed: the
                                group the row sits under decides it, and it is
                                what makes the id route back here. Without it
                                on screen there is nothing to tell you a name
                                typed under Azure OpenAI is stored as
                                `azure:<name>`. */}
                            {groupProvider && (
                              <span className="rounded-sm bg-muted px-1 font-mono text-xs text-muted-foreground">
                                {groupProvider}:
                              </span>
                            )}
                            <span>&ldquo;{customValue}&rdquo;</span>
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
                      aria-label={customValue}
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
                        Use &ldquo;{customValue}&rdquo;
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
                    aria-label={option.label}
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
                    aria-label={customValue}
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
                      Use &ldquo;{customValue}&rdquo;
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
