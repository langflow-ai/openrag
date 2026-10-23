"use client";

import {
  addDays,
  endOfMonth,
  isAfter,
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
import { isDateRangeFilterEnabled } from "@/lib/date-range-filter";
import {
  toLocalDayEndISOString,
  toLocalDayKey,
  toLocalDayStartISOString,
} from "@/lib/time-utils";
import { cn } from "@/lib/utils";

type Range = { from: Date; to: Date };

const EMPTY_DAYS: Record<string, number> = {};
const MAX_CUSTOM_DAYS = 3650;

interface Preset {
  id: string;
  label: string;
  range: (today: Date) => Range | null;
}

const PRESETS: Preset[] = [
  { id: "any", label: "Any time", range: () => null },
  { id: "today", label: "Today", range: (t) => ({ from: t, to: t }) },
  {
    id: "yesterday",
    label: "Yesterday",
    range: (t) => ({ from: subDays(t, 1), to: subDays(t, 1) }),
  },
  {
    id: "last-7",
    label: "Last 7 days",
    range: (t) => ({ from: subDays(t, 6), to: t }),
  },
  {
    id: "last-30",
    label: "Last 30 days",
    range: (t) => ({ from: subDays(t, 29), to: t }),
  },
  {
    id: "this-month",
    label: "This month",
    range: (t) => ({ from: startOfMonth(t), to: t }),
  },
  {
    id: "last-month",
    label: "Last month",
    range: (t) => {
      const prev = subMonths(t, 1);
      return { from: startOfMonth(prev), to: endOfMonth(prev) };
    },
  },
];

function formatDateLabel(date: Date): string {
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatShortLabel(date: Date, today: Date): string {
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(date.getFullYear() !== today.getFullYear() && { year: "numeric" }),
  });
}

function filterValues(values?: string[]) {
  const filtered = values?.filter((value) => value !== "*");
  return filtered && filtered.length > 0 ? filtered : undefined;
}

function countInRange(days: Record<string, number>, { from, to }: Range) {
  let total = 0;
  for (let d = startOfDay(from); !isAfter(d, to); d = addDays(d, 1)) {
    total += days[toLocalDayKey(d)] ?? 0;
  }
  return total;
}

function DensityMark({
  count,
  inverted,
}: {
  count: number;
  inverted: boolean;
}) {
  if (count <= 0) return <span aria-hidden className="h-1" />;
  return (
    <span
      aria-hidden
      data-testid="upload-density"
      data-density={count >= 5 ? "high" : count >= 2 ? "medium" : "low"}
      className={cn(
        "h-1 rounded-full",
        count >= 5 ? "w-5" : count >= 2 ? "w-3" : "w-1",
        inverted ? "bg-primary-foreground" : "bg-primary",
      )}
    />
  );
}

export function KnowledgeDateRangeFilter() {
  const { runMode } = useAuth();
  const isCloudBrand = useIsCloudBrand();
  if (!isDateRangeFilterEnabled(runMode, { isCloudBrand })) return null;
  return <DateRangeFilterPopover />;
}

function useToday(open: boolean) {
  // Refreshed while open so a page left running past midnight never keeps
  // yesterday as "today".
  const [today, setToday] = useState(() => startOfDay(new Date()));

  useEffect(() => {
    if (!open) return;
    const rollover = () => {
      const now = startOfDay(new Date());
      setToday((prev) => (isSameDay(prev, now) ? prev : now));
    };
    const nextMidnight = addDays(startOfDay(new Date()), 1);
    const timer = setTimeout(
      rollover,
      nextMidnight.getTime() - Date.now() + 1000,
    );
    return () => clearTimeout(timer);
  }, [open, today]);

  return [today, setToday] as const;
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

function CalendarPanel({
  draft,
  month,
  today,
  DayContent,
  onSelect,
  onMonthChange,
}: {
  draft: DateRange | undefined;
  month: Date;
  today: Date;
  DayContent: (props: DayContentProps) => React.JSX.Element;
  onSelect: (next: DateRange | undefined) => void;
  onMonthChange: (month: Date) => void;
}) {
  return (
    <div className="flex flex-1 flex-col items-center px-1 py-3 sm:px-4">
      <Calendar
        mode="range"
        selected={draft}
        onSelect={onSelect}
        month={month}
        onMonthChange={onMonthChange}
        toMonth={today}
        disabled={{ after: today }}
        components={{ DayContent }}
        classNames={{
          caption_label: "text-base font-semibold",
          head_cell: "w-9 text-xs font-normal text-muted-foreground sm:w-14",
          cell: cn(
            "relative h-11 w-9 p-0 text-center text-sm sm:h-12 sm:w-14",
            "[&:has([aria-selected])]:bg-accent",
            "first:[&:has([aria-selected])]:rounded-l-md",
            "last:[&:has([aria-selected])]:rounded-r-md",
            "focus-within:relative focus-within:z-20",
          ),
          day: "inline-flex h-11 w-9 items-center justify-center rounded-md p-0 font-normal hover:bg-accent/70 aria-selected:opacity-100 sm:h-12 sm:w-14",
        }}
      />
      <div className="mt-2 flex w-full items-center gap-4 px-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="h-1 w-1 rounded-full bg-primary" />1 upload
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1 w-3 rounded-full bg-primary" />
          2–4
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1 w-5 rounded-full bg-primary" />
          5+
        </span>
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

function DateRangeFilterPopover() {
  const { dateRange, setDateRange, parsedFilterData } = useKnowledgeFilter();
  const [open, setOpen] = useState(false);
  const [today, setToday] = useToday(open);
  const [draft, setDraft] = useState<DateRange | undefined>();
  const [month, setMonth] = useState<Date>(today);
  const [customDays, setCustomDays] = useState("");

  // Cover the shown month, every preset (last month, or 29 days back when that
  // is earlier), and the draft start so typed/custom ranges count correctly.
  const windowStart = min([
    startOfMonth(month),
    startOfMonth(subMonths(today, 1)),
    subDays(today, 29),
    ...(draft?.from ? [startOfDay(draft.from)] : []),
  ]);
  const { data: histogram } = useUploadHistogram(
    {
      start: toLocalDayStartISOString(windowStart),
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

  const handleOpenChange = (next: boolean) => {
    if (next) {
      const freshToday = startOfDay(new Date());
      setToday(freshToday);
      setDraft(
        dateRange?.from
          ? { from: dateRange.from, to: dateRange.to }
          : undefined,
      );
      setMonth(dateRange?.to ?? dateRange?.from ?? freshToday);
      setCustomDays("");
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

  const activePresetId = PRESETS.find((preset) => {
    const range = preset.range(today);
    if (!range || !draftRange) return !range && !draftRange;
    return (
      isSameDay(range.from, draftRange.from) &&
      isSameDay(range.to, draftRange.to)
    );
  })?.id;

  const handlePreset = (preset: Preset) => {
    const range = preset.range(today);
    setDraft(range ?? undefined);
    setCustomDays("");
    if (range) setMonth(range.to);
  };

  const handleCustomDays = (value: string) => {
    const digits = value.replace(/\D/g, "").slice(0, 4);
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
    setCustomDays("");
    setDraft(next);
  };

  const handleApply = () => {
    setDateRange(draftRange);
    setOpen(false);
  };

  const handleClear = () => {
    setDateRange(null);
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

  const label = dateRange?.from
    ? dateRange.to
      ? `${formatDateLabel(dateRange.from)} – ${formatDateLabel(dateRange.to)}`
      : formatDateLabel(dateRange.from)
    : null;

  const footerCount = presetCount(draftRange);
  const footerRange = draftRange
    ? isSameDay(draftRange.from, draftRange.to)
      ? formatShortLabel(draftRange.from, today)
      : `${formatShortLabel(draftRange.from, today)} – ${formatShortLabel(draftRange.to, today)}`
    : "Any time";

  return (
    <div className="flex h-full flex-shrink-0 items-stretch">
      <Popover open={open} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            className={cn(
              "h-auto gap-2 rounded-none px-3 text-sm hover:bg-accent hover:text-foreground",
              dateRange && "bg-accent text-foreground",
            )}
            aria-label={label ?? "Filter by date range"}
          >
            <CalendarIcon className="h-4 w-4 flex-shrink-0 text-[var(--icon-primary)]" />
            {/* The range label is wide; show it only once the bar has room for it. */}
            <span className="hidden max-w-[16rem] truncate xl:inline">
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
          className="inline-flex w-8 flex-shrink-0 items-center justify-center bg-accent text-muted-foreground transition-colors hover:text-foreground"
          onClick={handleClear}
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}
