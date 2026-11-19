"use client";

import {
  addDays,
  isSameDay,
  min,
  startOfDay,
  startOfMonth,
  subDays,
  subMonths,
} from "date-fns";
import { CalendarIcon, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { DateRange, DayContentProps } from "react-day-picker";
import { useUploadHistogram } from "@/app/api/queries/useUploadHistogram";
import {
  CalendarPanel,
  DensityMark,
  useToday,
} from "@/components/knowledge-date-range-shared";
import { KnowledgeDateRangeV2 } from "@/components/knowledge-date-range-v2";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import {
  isDateRangeFilterEnabled,
  isDateRangeV2Enabled,
} from "@/lib/date-range-filter";
import {
  countInRange,
  describeToolbarRange,
  EMPTY_DAYS,
  earlierInstant,
  filterValues,
  formatDateLabel,
  formatShortLabel,
  laterInstant,
  PRESETS,
  type Preset,
  type Range,
} from "@/lib/knowledge-date-range";
import {
  type DateRangeValue,
  foreignTimeZone,
  type SavedDateRange,
  viewerTimeZone,
} from "@/lib/saved-date-range";
import {
  toLocalDayEndISOString,
  toLocalDayKey,
  toLocalDayStartISOString,
} from "@/lib/time-utils";
import { cn } from "@/lib/utils";

const MAX_CUSTOM_DAYS = 3650;

/** Toolbar picker: edits the temporary range of the Knowledge page. */
export function KnowledgeDateRangeFilter() {
  const { dateRange, setDateRange, parsedFilterData, effectiveDateRange } =
    useKnowledgeFilter();
  const enabled = useDateRangeFilterEnabled();
  const v2 = useDateRangeV2Enabled();
  if (!enabled) return null;
  if (v2) return <KnowledgeDateRangeV2 />;
  return (
    <DateRangePicker
      value={dateRange}
      onChange={setDateRange}
      facetFilters={parsedFilterData?.filters}
      savedRange={effectiveDateRange}
    />
  );
}

export function useDateRangeFilterEnabled(): boolean {
  const { runMode } = useAuth();
  const isCloudBrand = useIsCloudBrand();
  return isDateRangeFilterEnabled(runMode, { isCloudBrand });
}

/** Date range v2 gate. Nothing consumes this yet. */
export function useDateRangeV2Enabled(): boolean {
  const { runMode, dateRangeV2 } = useAuth();
  const isCloudBrand = useIsCloudBrand();
  return isDateRangeV2Enabled(runMode, dateRangeV2, { isCloudBrand });
}

function QuickRanges({
  today,
  activePresetId,
  presetCount,
  customDays,
  onPreset,
  onCustomDays,
}: {
  today: Date;
  activePresetId: string | undefined;
  presetCount: (range: Range | null) => number | undefined;
  customDays: string;
  onPreset: (preset: Preset) => void;
  onCustomDays: (value: string) => void;
}) {
  return (
    <div className="border-b py-2 md:w-60 md:flex-shrink-0 md:border-b-0 md:border-r md:py-4">
      <p className="hidden px-4 pb-2 text-xs text-muted-foreground md:block">
        Quick ranges
      </p>
      {/* A scrolling row on narrow screens, a list beside the calendar otherwise. */}
      <div className="flex gap-1 overflow-x-auto px-2 md:flex-col md:gap-0 md:px-0">
        {PRESETS.map((preset) => {
          const count = presetCount(preset.range(today));
          const active = preset.id === activePresetId;
          return (
            <button
              key={preset.id}
              type="button"
              aria-pressed={active}
              onClick={() => onPreset(preset)}
              className={cn(
                "flex flex-shrink-0 items-center justify-between gap-4 whitespace-nowrap rounded-md px-3 py-2 text-sm transition-colors hover:bg-accent md:rounded-none md:px-4 md:py-2.5",
                active && "bg-accent font-medium text-foreground",
              )}
            >
              <span>{preset.label}</span>
              <span className="font-mono text-xs tabular-nums text-muted-foreground">
                {count ?? ""}
              </span>
            </button>
          );
        })}
      </div>
      <div className="mt-2 flex items-center gap-2 px-4 md:mt-3">
        <label
          htmlFor="custom-days"
          className="whitespace-nowrap text-sm text-muted-foreground"
        >
          Last
        </label>
        <input
          id="custom-days"
          type="text"
          inputMode="numeric"
          placeholder="90"
          aria-label="Number of days"
          value={customDays}
          onChange={(e) => onCustomDays(e.target.value)}
          className="h-8 w-16 rounded-md border bg-background px-2 text-sm tabular-nums"
        />
        <span className="text-sm text-muted-foreground">days</span>
      </div>
    </div>
  );
}

function PopoverFooter({
  footerCount,
  footerRange,
  onCancel,
  onApply,
}: {
  footerCount: number | undefined;
  footerRange: string;
  onCancel: () => void;
  onApply: () => void;
}) {
  return (
    <div className="flex flex-col border-t md:flex-row md:items-stretch">
      <p className="flex-1 px-4 py-3 text-sm" aria-live="polite">
        {footerCount !== undefined && (
          <>
            <span className="font-semibold">
              {footerCount} {footerCount === 1 ? "file" : "files"}
            </span>
            {" · "}
          </>
        )}
        <span className="text-muted-foreground">{footerRange}</span>
      </p>
      <div className="flex border-t md:border-t-0">
        <Button
          type="button"
          variant="secondary"
          ignoreTitleCase
          className="h-auto flex-1 rounded-none px-6 py-3 md:flex-none"
          onClick={onCancel}
        >
          Cancel
        </Button>
        <Button
          type="button"
          ignoreTitleCase
          className="h-auto flex-1 rounded-none px-8 py-3 md:flex-none"
          onClick={onApply}
        >
          Apply filter
        </Button>
      </div>
    </div>
  );
}

export interface DateRangePickerProps {
  value: DateRangeValue | null;
  onChange: (range: DateRangeValue | null) => void;
  /** Facet selections that scope the upload-density marks (not the range itself). */
  facetFilters?: {
    data_sources?: string[];
    document_types?: string[];
    owners?: string[];
    connector_types?: string[];
  };
  /**
   * Bounds + timezone context behind `value`. While the user has not edited the
   * range, upload counts use this timezone so they agree with retrieval.
   */
  savedRange?: SavedDateRange;
}

/**
 * Controlled date-range picker. It owns only the popover draft; the caller
 * decides what applying or clearing means (temporary toolbar range, or an
 * unsaved draft inside the Knowledge Filter editor).
 */
export function DateRangePicker({
  value: dateRange,
  onChange,
  facetFilters,
  savedRange,
}: DateRangePickerProps) {
  const [open, setOpen] = useState(false);
  const [today, setToday] = useToday(open);
  const [draft, setDraft] = useState<DateRange | undefined>();
  const [month, setMonth] = useState<Date>(today);
  const [customDays, setCustomDays] = useState("");
  // False until the user changes the draft; an unchanged Apply keeps the range as saved.
  const [edited, setEdited] = useState(false);
  const savedTimeZone = foreignTimeZone(savedRange);
  const countInSavedZone = !edited && savedTimeZone !== null;

  // Cover the shown month, every preset (last month, or 29 days back when that
  // is earlier), and the draft start so typed/custom ranges count correctly.
  const windowStart = min([
    startOfMonth(month),
    startOfMonth(subMonths(today, 1)),
    subDays(today, 29),
    ...(draft?.from ? [startOfDay(draft.from)] : []),
  ]);
  // An unedited saved range is counted in the zone it was saved in, over a
  // window that includes its exact bounds; edits switch to the viewer's zone.
  const windowStartISO = toLocalDayStartISOString(windowStart);
  const windowEndISO = toLocalDayEndISOString(today);
  const { data: histogram } = useUploadHistogram(
    {
      start: countInSavedZone
        ? earlierInstant(windowStartISO, savedRange?.createdAfter)
        : windowStartISO,
      end: countInSavedZone
        ? laterInstant(windowEndISO, savedRange?.createdBefore)
        : windowEndISO,
      tz: countInSavedZone && savedTimeZone ? savedTimeZone : viewerTimeZone(),
      connectorType: filterValues(facetFilters?.connector_types),
      mimetype: filterValues(facetFilters?.document_types),
      owner: filterValues(facetFilters?.owners),
      dataSources: filterValues(facetFilters?.data_sources),
    },
    { enabled: open },
  );
  const days = histogram?.days ?? EMPTY_DAYS;

  const handleOpenChange = (next: boolean) => {
    if (next) {
      const freshToday = startOfDay(new Date());
      setToday(freshToday);
      setDraft(
        dateRange?.from || dateRange?.to
          ? { from: dateRange.from, to: dateRange.to }
          : undefined,
      );
      setMonth(dateRange?.to ?? dateRange?.from ?? freshToday);
      setCustomDays("");
      setEdited(false);
    }
    setOpen(next);
  };

  const draftRange: Range | null = draft?.from
    ? { from: draft.from, to: draft.to ?? draft.from }
    : null;

  const presetCount = (range: Range | null) =>
    histogram
      ? range
        ? countInRange(days, range)
        : histogram.total
      : undefined;

  // A saved range with only one bound is shown as such until it is edited.
  const openEndedUnedited =
    !edited && Boolean(dateRange) && !(dateRange?.from && dateRange?.to);

  const activePresetId = openEndedUnedited
    ? undefined
    : PRESETS.find((preset) => {
        const presetRange = preset.range(today);
        if (!presetRange || !draftRange) return !presetRange && !draftRange;
        return (
          isSameDay(presetRange.from, draftRange.from) &&
          isSameDay(presetRange.to, draftRange.to)
        );
      })?.id;

  const handlePreset = (preset: Preset) => {
    const range = preset.range(today);
    setEdited(true);
    setDraft(range ?? undefined);
    setCustomDays("");
    if (range) setMonth(range.to);
  };

  const handleCustomDays = (value: string) => {
    const digits = value.replace(/\D/g, "").slice(0, 4);
    setEdited(true);
    setCustomDays(digits);
    const n = Math.min(Number.parseInt(digits, 10), MAX_CUSTOM_DAYS);
    if (!n) {
      setDraft(undefined);
      return;
    }
    const range = { from: subDays(today, n - 1), to: today };
    setDraft(range);
    setMonth(range.to);
  };

  const handleCalendarSelect = (next: DateRange | undefined) => {
    setEdited(true);
    setCustomDays("");
    setDraft(next);
  };

  const handleApply = () => {
    // Re-applying what was shown must not reinterpret it: an open-ended range
    // has no second day to fill in, and the saved bounds stay as they are.
    if (edited) onChange(draftRange);
    setOpen(false);
  };

  const handleClear = () => {
    onChange(null);
    setOpen(false);
  };

  // Rebuilt only when the counts change, so day cells don't remount per render.
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
              count={days[toLocalDayKey(date)] ?? 0}
              inverted={isEnd}
            />
          </span>
        );
      },
    [days],
  );

  const label = describeToolbarRange(dateRange, formatDateLabel);

  // A saved one-sided range has no closed draftRange; describe it as it is.
  const footerCount = openEndedUnedited ? undefined : presetCount(draftRange);
  const footerRange = openEndedUnedited
    ? (describeToolbarRange(dateRange, (d) => formatShortLabel(d, today)) ??
      "Any time")
    : draftRange
      ? isSameDay(draftRange.from, draftRange.to)
        ? formatShortLabel(draftRange.from, today)
        : `${formatShortLabel(draftRange.from, today)} – ${formatShortLabel(draftRange.to, today)}`
      : "Any time";

  return (
    <div className="flex flex-shrink-0 items-center gap-1">
      <Popover open={open} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            className={cn("flex-shrink-0 rounded-lg", dateRange && "bg-accent")}
            aria-label={label ?? "Filter by date range"}
          >
            <CalendarIcon className="mr-2 h-4 w-4 flex-shrink-0" />
            <span className="max-w-[16rem] truncate">
              {label ?? "Date range"}
            </span>
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className="w-[min(52rem,calc(100vw-2rem))] overflow-hidden p-0"
          align="end"
          collisionPadding={16}
        >
          <div className="flex flex-col md:flex-row">
            <QuickRanges
              today={today}
              activePresetId={activePresetId}
              presetCount={presetCount}
              customDays={customDays}
              onPreset={handlePreset}
              onCustomDays={handleCustomDays}
            />
            <CalendarPanel
              draft={draft}
              month={month}
              today={today}
              DayContent={DayContent}
              onSelect={handleCalendarSelect}
              onMonthChange={setMonth}
            />
          </div>
          {savedTimeZone && (
            <p className="border-t px-4 py-2 text-xs text-muted-foreground">
              Saved in {savedTimeZone}. Days you pick here use your time zone (
              {viewerTimeZone()}).
            </p>
          )}
          <PopoverFooter
            footerCount={footerCount}
            footerRange={footerRange}
            onCancel={() => setOpen(false)}
            onApply={handleApply}
          />
        </PopoverContent>
      </Popover>
      {dateRange && (
        <button
          type="button"
          aria-label="Clear date range"
          className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          onClick={handleClear}
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}
