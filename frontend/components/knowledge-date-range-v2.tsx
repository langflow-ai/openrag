"use client";

import {
  isSameDay,
  min,
  startOfDay,
  startOfMonth,
  subDays,
  subMonths,
} from "date-fns";
import { CalendarIcon, Maximize2, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { DateRange, DayContentProps } from "react-day-picker";
import { useUploadHistogram } from "@/app/api/queries/useUploadHistogram";
import {
  CalendarPanel,
  DensityMark,
  useToday,
} from "@/components/knowledge-date-range-filter";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import {
  countWithinCoverage,
  describeToolbarRange,
  EMPTY_DAYS,
  filterValues,
  formatDateLabel,
  MAX_HISTOGRAM_DAYS,
  type Preset,
  type Range,
  V2_PRESETS,
} from "@/lib/knowledge-date-range";
import type { SavedDateRange } from "@/lib/saved-date-range";
import {
  toLocalDayEndISOString,
  toLocalDayKey,
  toLocalDayStartISOString,
} from "@/lib/time-utils";
import { cn } from "@/lib/utils";

const hasBounds = (r: SavedDateRange) =>
  Boolean(r.createdAfter || r.createdBefore);

/** Compact date-range popover (V2). Rendered only behind the V2 flag. */
export function KnowledgeDateRangeV2() {
  const { dateRange, effectiveDateRange, parsedFilterData, setDateRange } =
    useKnowledgeFilter();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"quick" | "custom">("quick");
  const [today, setToday] = useToday(open);
  const [draft, setDraft] = useState<DateRange | undefined>();
  const [month, setMonth] = useState<Date>(today);
  // False until the user changes the draft; an unchanged Apply keeps the saved range.
  const [edited, setEdited] = useState(false);

  // Toolbar dates drive the Knowledge table and seed new filters, exactly like
  // the classic picker. A table/filters scope selector is deliberately absent
  // until filter previews and counts can respond to a filter-side range.
  const shown = dateRange;
  const label = describeToolbarRange(shown ?? null, formatDateLabel);
  const hasRange = hasBounds(effectiveDateRange);

  const earliest = startOfDay(subDays(today, MAX_HISTOGRAM_DAYS));
  // Cover everything the popover displays: each preset (quarters included), the
  // visible month, and the custom draft. The cap keeps the request bounded.
  const presetStarts = V2_PRESETS.map(
    (preset) => preset.range(today)?.from,
  ).filter((d): d is Date => Boolean(d));
  const windowStart = min([
    startOfMonth(month),
    startOfMonth(subMonths(today, 1)),
    subDays(today, 29),
    ...presetStarts,
    ...(draft?.from ? [startOfDay(draft.from)] : []),
  ]);
  const clampedStart = windowStart < earliest ? earliest : windowStart;
  const { data: histogram, isPlaceholderData } = useUploadHistogram(
    {
      start: toLocalDayStartISOString(clampedStart),
      end: toLocalDayEndISOString(today),
      tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
      connectorType: filterValues(parsedFilterData?.filters?.connector_types),
      mimetype: filterValues(parsedFilterData?.filters?.document_types),
      owner: filterValues(parsedFilterData?.filters?.owners),
      dataSources: filterValues(parsedFilterData?.filters?.data_sources),
    },
    { enabled: open },
  );
  const days = histogram?.days ?? EMPTY_DAYS;
  // undefined = still loading; null = the window does not cover the range.
  const countFor = (range: Range | null): number | null | undefined => {
    if (!histogram || isPlaceholderData) return undefined;
    if (!range) return histogram.total;
    return countWithinCoverage(days, range, clampedStart);
  };

  // Days before the requested window, or while a changed window is still
  // loading, have no data yet; they must not read as "no uploads".
  const histogramReady = Boolean(histogram) && !isPlaceholderData;
  const coveredFrom = startOfDay(clampedStart);

  const DayContent = useMemo(
    () =>
      function DayContent({ date, activeModifiers }: DayContentProps) {
        const isEnd =
          Boolean(activeModifiers.range_start) ||
          Boolean(activeModifiers.range_end);
        return (
          <span className="flex flex-col items-center gap-1">
            <span data-day-number>{date.getDate()}</span>
            <DensityMark
              count={
                histogramReady && startOfDay(date) >= coveredFrom
                  ? (days[toLocalDayKey(date)] ?? 0)
                  : 0
              }
              inverted={isEnd}
            />
          </span>
        );
      },
    [days, histogramReady, coveredFrom],
  );

  const handleOpenChange = (next: boolean) => {
    if (next) {
      const fresh = startOfDay(new Date());
      setToday(fresh);
      setView("quick");
      // Start the custom calendar from the current range, like the classic picker.
      setDraft(
        shown?.from || shown?.to
          ? { from: shown.from, to: shown.to }
          : undefined,
      );
      setMonth(shown?.to ?? shown?.from ?? fresh);
      setEdited(false);
    }
    setOpen(next);
  };

  const apply = (range: DateRange | null) => {
    setDateRange(
      range?.from ? { from: range.from, to: range.to ?? range.from } : null,
    );
    setOpen(false);
  };

  const activePresetId = V2_PRESETS.find((preset) => {
    const r = preset.range(today);
    if (!r) return !shown?.from && !shown?.to;
    // A closed preset matches only a closed range; "From today" is not "Today".
    if (!shown?.from || !shown?.to) return false;
    return isSameDay(r.from, shown.from) && isSameDay(r.to, shown.to);
  })?.id;

  return (
    <div className="flex flex-shrink-0 items-center gap-1">
      <Popover open={open} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            className={cn("flex-shrink-0 rounded-lg", hasRange && "bg-accent")}
            aria-label={label ?? "Filter by date range"}
          >
            <CalendarIcon className="mr-2 h-4 w-4 flex-shrink-0" />
            <span className="max-w-[16rem] truncate">
              {label ?? "Date range"}
            </span>
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="end"
          collisionPadding={16}
          className={cn(
            "overflow-hidden p-0",
            view === "custom" ? "w-[min(26rem,calc(100vw-2rem))]" : "w-72",
          )}
        >
          {view === "quick" ? (
            <>
              <p className="px-3 pt-3 pb-1 text-xs text-muted-foreground">
                Quick ranges
              </p>
              {V2_PRESETS.map((preset: Preset) => {
                const range = preset.range(today);
                const count = countFor(range);
                return (
                  <button
                    key={preset.id}
                    type="button"
                    aria-pressed={preset.id === activePresetId}
                    onClick={() =>
                      apply(range ? { from: range.from, to: range.to } : null)
                    }
                    className={cn(
                      "flex w-full items-center justify-between px-4 py-2.5 text-sm transition-colors hover:bg-accent",
                      preset.id === activePresetId &&
                        "bg-accent font-medium text-foreground",
                    )}
                  >
                    <span>{preset.label}</span>
                    <span className="font-mono text-xs tabular-nums text-muted-foreground">
                      {count === null ? (
                        <span title="Count unavailable for this range">–</span>
                      ) : (
                        (count ?? "")
                      )}
                    </span>
                  </button>
                );
              })}
              <div className="flex items-center justify-between border-t px-4 py-2.5">
                <button
                  type="button"
                  onClick={() => setView("custom")}
                  className="flex items-center gap-2 text-sm text-primary"
                >
                  <CalendarIcon className="h-4 w-4" />
                  Custom range
                </button>
                <button
                  type="button"
                  aria-label="Expand custom range"
                  onClick={() => setView("custom")}
                  className="text-primary"
                >
                  <Maximize2 className="h-4 w-4" />
                </button>
              </div>
            </>
          ) : (
            <>
              <CalendarPanel
                draft={draft}
                month={month}
                today={today}
                DayContent={DayContent}
                onSelect={(next) => {
                  setEdited(true);
                  setDraft(next);
                }}
                onMonthChange={setMonth}
              />
              <div className="flex border-t">
                <Button
                  type="button"
                  variant="secondary"
                  ignoreTitleCase
                  className="h-auto flex-1 rounded-none py-3"
                  onClick={() => setView("quick")}
                >
                  Back
                </Button>
                <Button
                  type="button"
                  ignoreTitleCase
                  className="h-auto flex-1 rounded-none py-3"
                  disabled={edited ? !draft?.from : !shown?.from && !shown?.to}
                  onClick={() =>
                    edited ? apply(draft ?? null) : setOpen(false)
                  }
                >
                  Apply filter
                </Button>
              </div>
            </>
          )}
        </PopoverContent>
      </Popover>
      {hasRange && (
        <button
          type="button"
          aria-label="Clear date range"
          className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          onClick={() => {
            setDateRange(null);
            setDraft(undefined);
            setEdited(false);
          }}
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}
