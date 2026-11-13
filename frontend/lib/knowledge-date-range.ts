import {
  addDays,
  endOfMonth,
  endOfQuarter,
  isAfter,
  isSameDay,
  startOfDay,
  startOfMonth,
  startOfQuarter,
  subDays,
  subMonths,
  subQuarters,
} from "date-fns";
import type { DateRangeValue } from "@/lib/saved-date-range";
import { toLocalDayKey } from "@/lib/time-utils";

export type Range = { from: Date; to: Date };

export const EMPTY_DAYS: Record<string, number> = {};

/**
 * The upload-count request never reaches further back than this. It bounds the
 * request only: the calendar stays navigable and any date can still be picked.
 */
export const MAX_HISTOGRAM_DAYS = 730;

export interface Preset {
  id: string;
  label: string;
  range: (today: Date) => Range | null;
}

export const PRESETS: Preset[] = [
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

/** Classic presets plus quarters (V2 only; the classic list is unchanged). */
export const V2_PRESETS: Preset[] = [
  ...PRESETS,
  {
    id: "this-quarter",
    label: "This quarter",
    range: (t) => ({ from: startOfQuarter(t), to: t }),
  },
  {
    id: "last-quarter",
    label: "Last quarter",
    range: (t) => {
      const prev = subQuarters(t, 1);
      return { from: startOfQuarter(prev), to: endOfQuarter(prev) };
    },
  },
];

export function formatDateLabel(date: Date): string {
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatShortLabel(date: Date, today: Date): string {
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(date.getFullYear() !== today.getFullYear() && { year: "numeric" }),
  });
}

/** "A – B", a single day, or "From A" / "Until B" for a one-sided saved range. */
export function describeToolbarRange(
  range: DateRangeValue | null,
  format: (date: Date) => string,
): string | null {
  if (range?.from && range.to) {
    return isSameDay(range.from, range.to)
      ? format(range.from)
      : `${format(range.from)} – ${format(range.to)}`;
  }
  if (range?.from) return `From ${format(range.from)}`;
  if (range?.to) return `Until ${format(range.to)}`;
  return null;
}

export function filterValues(values?: string[]) {
  const filtered = values?.filter((value) => value !== "*");
  return filtered && filtered.length > 0 ? filtered : undefined;
}

export function countInRange(
  days: Record<string, number>,
  { from, to }: Range,
) {
  let total = 0;
  for (let d = startOfDay(from); !isAfter(d, to); d = addDays(d, 1)) {
    total += days[toLocalDayKey(d)] ?? 0;
  }
  return total;
}

/**
 * Upload count for `range`, or null when the histogram window starts after the
 * range does (missing buckets would read as zero). Open-ended "any time" is
 * answered from the all-time total instead and never reaches this.
 */
export function countWithinCoverage(
  days: Record<string, number>,
  range: Range,
  coveredFrom: Date,
): number | null {
  if (startOfDay(range.from) < startOfDay(coveredFrom)) return null;
  return countInRange(days, range);
}

export function earlierInstant(iso: string, other?: string): string {
  return other && new Date(other) < new Date(iso) ? other : iso;
}

export function laterInstant(iso: string, other?: string): string {
  return other && new Date(other) > new Date(iso) ? other : iso;
}
