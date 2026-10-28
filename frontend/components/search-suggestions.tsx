import { FileIcon, Info, Search } from "lucide-react";
import {
  type KeyboardEvent,
  type ReactElement,
  useId,
  useMemo,
  useState,
} from "react";
import { toast } from "sonner";
import {
  type SearchSuggestResult,
  SUGGEST_MAX_CHARS,
  SUGGEST_MIN_CHARS,
  type SuggestFile,
  useSearchSuggestions,
} from "@/app/api/queries/useGetSearchSuggestions";
import {
  BOLD_MATCH_CLASS,
  HighlightedText,
  PREVIEW_TEXT_CLASS,
} from "@/components/highlighted-text";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/ui/popover";
import type { FilterInput } from "@/lib/filter-normalization";
import { splitOnQuery } from "@/lib/search-preview";
import { cn } from "@/lib/utils";

/**
 * Clamp typed or pasted search text to the suggestion length cap and tell the
 * user when input was dropped. The fixed toast id keeps held keys from stacking
 * popups.
 */
export function limitSearchInput(value: string): string {
  const characters = [...value];
  if (characters.length <= SUGGEST_MAX_CHARS) return value;
  toast.error(`Search is limited to ${SUGGEST_MAX_CHARS} characters.`, {
    id: "search-query-limit",
  });
  return characters.slice(0, SUGGEST_MAX_CHARS).join("");
}

export type SuggestionItem =
  | {
      kind: "suggestion";
      key: string;
      text: string;
      files: number;
      chunks: number;
    }
  | { kind: "file"; key: string; file: SuggestFile };

function buildSuggestionItems(
  data: SearchSuggestResult | undefined,
): SuggestionItem[] {
  if (!data) return [];
  return [
    ...data.suggestions.map(
      (suggestion): SuggestionItem => ({
        kind: "suggestion",
        key: `s:${suggestion.text}`,
        ...suggestion,
      }),
    ),
    ...data.files.map(
      (file): SuggestionItem => ({
        kind: "file",
        key: `f:${file.filename}`,
        file,
      }),
    ),
  ];
}

interface UseSearchSuggestionsBoxOptions {
  query: string;
  filters: FilterInput | undefined;
  enabled: boolean;
  scoreThreshold?: number;
  onPickSuggestion: (text: string) => void;
  onPickFile: (filename: string) => void;
}

/**
 * State and keyboard handling for the search suggestions dropdown.
 *
 * Arrow keys move through the rows, Enter opens the highlighted row (and falls
 * through to a normal search when none is highlighted), Escape dismisses.
 */
export function useSearchSuggestionsBox({
  query,
  filters,
  enabled,
  scoreThreshold,
  onPickSuggestion,
  onPickFile,
}: UseSearchSuggestionsBoxOptions) {
  const listId = useId();
  const [focused, setFocused] = useState(false);
  const [dismissedQuery, setDismissedQuery] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState(-1);

  const { data, isRefining, isError } = useSearchSuggestions(
    query,
    filters,
    enabled && focused,
    scoreThreshold,
  );
  const items = useMemo(() => buildSuggestionItems(data), [data]);

  const [prevItems, setPrevItems] = useState(items);
  if (prevItems !== items) {
    setPrevItems(items);
    setActiveIndex(-1);
  }

  // Compared trimmed: submitting commits the trimmed text, which would
  // otherwise differ from the dismissed value and reopen the dropdown.
  const trimmedQuery = query.trim();
  const open =
    enabled &&
    focused &&
    trimmedQuery.length >= SUGGEST_MIN_CHARS &&
    dismissedQuery !== trimmedQuery;

  const pick = (item: SuggestionItem) => {
    if (item.kind === "suggestion") {
      setDismissedQuery(item.text);
      onPickSuggestion(item.text);
    } else {
      setDismissedQuery(trimmedQuery);
      onPickFile(item.file.filename);
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!open || event.nativeEvent.isComposing) return;
    const count = items.length;

    if (event.key === "ArrowDown" && count > 0) {
      event.preventDefault();
      setActiveIndex((index) => (index + 1 >= count ? -1 : index + 1));
    } else if (event.key === "ArrowUp" && count > 0) {
      event.preventDefault();
      setActiveIndex((index) => (index <= -1 ? count - 1 : index - 1));
    } else if (event.key === "Enter" && items[activeIndex]) {
      event.preventDefault();
      pick(items[activeIndex]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      setDismissedQuery(trimmedQuery);
    }
  };

  const optionId = (index: number) => `${listId}-option-${index}`;

  return {
    open,
    dismiss: () => setDismissedQuery(trimmedQuery),
    data,
    items,
    isRefining,
    isError,
    activeIndex,
    setActiveIndex,
    pick,
    listId,
    optionId,
    onOpenChange: (next: boolean) => {
      if (!next) setDismissedQuery(trimmedQuery);
    },
    anchorProps: { "data-search-suggest-anchor": "" },
    inputProps: {
      role: "combobox" as const,
      "aria-autocomplete": "list" as const,
      "aria-expanded": open,
      "aria-controls": listId,
      "aria-activedescendant":
        open && activeIndex >= 0 ? optionId(activeIndex) : undefined,
      autoComplete: "off",
      onFocus: () => setFocused(true),
      onBlur: () => setFocused(false),
      onKeyDown: handleKeyDown,
    },
  };
}

type SearchSuggestionsBox = ReturnType<typeof useSearchSuggestionsBox>;

function MatchedText({ text, query }: { text: string; query: string }) {
  const { before, match, after } = splitOnQuery(text, query);
  return (
    <span className="truncate">
      {before}
      {match && <strong className={BOLD_MATCH_CLASS}>{match}</strong>}
      {after}
    </span>
  );
}

function countLabel(count: number, noun: string) {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function SectionLabel({ children }: { children: string }) {
  return (
    <div
      role="presentation"
      className="px-3 pt-2 pb-1 text-xs font-medium text-muted-foreground"
    >
      {children}
    </div>
  );
}

function SuggestionRows({
  box,
  query,
}: {
  box: SearchSuggestionsBox;
  query: string;
}) {
  const suggestionCount = box.items.filter(
    (item) => item.kind === "suggestion",
  ).length;
  const rows = box.items.map((item, index) => {
    const active = index === box.activeIndex;
    const base = cn(
      "flex w-full items-start gap-3 px-3 py-2 text-left text-sm",
      active ? "bg-accent text-accent-foreground" : "hover:bg-accent/60",
    );
    const handlers = {
      id: box.optionId(index),
      role: "option" as const,
      "aria-selected": active,
      type: "button" as const,
      // Keep focus in the input so typing continues after a click.
      onMouseDown: (event: React.MouseEvent) => event.preventDefault(),
      onMouseEnter: () => box.setActiveIndex(index),
      onClick: () => box.pick(item),
    };

    if (item.kind === "suggestion") {
      return (
        <button key={item.key} {...handlers} className={base}>
          <Search className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <MatchedText text={item.text} query={query} />
          <span className="ml-auto shrink-0 text-xs text-muted-foreground">
            {countLabel(item.files, "file")} ·{" "}
            {countLabel(item.chunks, "chunk")}
          </span>
        </button>
      );
    }

    const { file } = item;
    return (
      <button key={item.key} {...handlers} className={base}>
        <FileIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="flex min-w-0 flex-1 flex-col">
          <MatchedText text={file.filename} query={query} />
          {file.preview &&
            (file.preview.kind === "keyword" ? (
              <HighlightedText
                highlights={[file.preview.text]}
                fallbackText=""
                className={cn("block truncate text-xs", PREVIEW_TEXT_CLASS)}
                markClassName={BOLD_MATCH_CLASS}
              />
            ) : (
              <span
                className={cn("block truncate text-xs", PREVIEW_TEXT_CLASS)}
              >
                {file.preview.text}
              </span>
            ))}
        </span>
        <span className="ml-auto shrink-0 text-xs text-muted-foreground">
          Open file
        </span>
      </button>
    );
  });

  return (
    <>
      {suggestionCount > 0 && <SectionLabel>Suggestions</SectionLabel>}
      {rows.slice(0, suggestionCount)}
      {rows.length > suggestionCount && <SectionLabel>Files</SectionLabel>}
      {rows.slice(suggestionCount)}
    </>
  );
}

interface SearchSuggestionsPopoverProps {
  box: SearchSuggestionsBox;
  query: string;
  /** The single element the dropdown anchors to (spread `box.anchorProps` on it). */
  children: ReactElement;
}

export function SearchSuggestionsPopover({
  box,
  query,
  children,
}: SearchSuggestionsPopoverProps) {
  const trimmed = query.trim();
  const empty = box.data && box.items.length === 0;

  return (
    <Popover open={box.open} onOpenChange={box.onOpenChange}>
      <PopoverAnchor asChild>{children}</PopoverAnchor>
      <PopoverContent
        align="start"
        sideOffset={4}
        className="w-(--radix-popover-trigger-width) min-w-72 overflow-hidden rounded-none p-0"
        onOpenAutoFocus={(event) => event.preventDefault()}
        onCloseAutoFocus={(event) => event.preventDefault()}
        // Radix reports clicks on the input as "outside"; ignore them so the
        // dropdown does not flicker closed while the user is typing.
        onInteractOutside={(event) => {
          const target = event.target as HTMLElement | null;
          if (target?.closest("[data-search-suggest-anchor]")) {
            event.preventDefault();
          }
        }}
      >
        <div
          id={box.listId}
          role="listbox"
          aria-label={`Search suggestions for ${trimmed}`}
          className="max-h-96 overflow-y-auto pb-1"
        >
          {!box.data && !box.isError && (
            <div
              role="presentation"
              className="px-3 py-3 text-sm text-muted-foreground"
            >
              Searching…
            </div>
          )}
          {box.isError && (
            <div
              role="presentation"
              className="px-3 py-3 text-sm text-muted-foreground"
            >
              Suggestions unavailable. Press Enter to search.
            </div>
          )}
          {empty && (
            <div
              role="presentation"
              className="px-3 py-3 text-sm text-muted-foreground"
            >
              No suggestions. Press Enter to search.
            </div>
          )}
          <SuggestionRows box={box} query={trimmed} />
        </div>
        <div className="flex items-center gap-2 border-t px-3 py-2 text-xs text-muted-foreground">
          <Info className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">
            Searching file names and content ·{" "}
            {box.isRefining
              ? "Refining with meaning…"
              : "Hybrid (keyword + meaning)"}
          </span>
        </div>
      </PopoverContent>
    </Popover>
  );
}
