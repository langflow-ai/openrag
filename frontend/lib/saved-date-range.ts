/**
 * Date range persisted on a Knowledge Filter.
 *
 * Two representations travel together and play different roles:
 *  - `createdAfter` / `createdBefore` are explicit UTC instants. They are the
 *    only values used for retrieval, so a shared filter never shifts its window.
 *  - `context` (calendar days + IANA timezone) is what the picker displays.
 *
 * An unchanged range keeps its saved bounds verbatim in any viewer timezone;
 * bounds are only recomputed (in the viewer's timezone) when the user edits it.
 */

import {
  toLocalDayEndISOString,
  toLocalDayKey,
  toLocalDayStartISOString,
} from "@/lib/time-utils";

export interface DateRangeContext {
  from?: string;
  to?: string;
  timezone?: string;
}

export interface SavedDateRange {
  createdAfter?: string;
  createdBefore?: string;
  context?: DateRangeContext;
}

export interface DateRangeValue {
  from?: Date;
  to?: Date;
}

/** No bounds at all: "any time". Used as an explicit override that clears a saved range. */
export const NO_DATE_RANGE: SavedDateRange = Object.freeze({});

const DAY_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}

export function parseCalendarDay(day: string): Date | null {
  const match = DAY_RE.exec(day);
  if (!match) return null;
  const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const date = new Date(y, m - 1, d);
  return date.getFullYear() === y &&
    date.getMonth() === m - 1 &&
    date.getDate() === d
    ? date
    : null;
}

export function viewerTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

export function hasDateBounds(range: SavedDateRange | undefined): boolean {
  return Boolean(range?.createdAfter || range?.createdBefore);
}

/** Read the optional date fields out of parsed (already JSON-decoded) query data. */
export function parseSavedDateRange(raw: unknown): SavedDateRange {
  const data = (raw ?? {}) as {
    filters?: { created_after?: unknown; created_before?: unknown };
    date_range_context?: {
      from?: unknown;
      to?: unknown;
      timezone?: unknown;
    } | null;
  };
  const createdAfter = nonEmptyString(data.filters?.created_after);
  const createdBefore = nonEmptyString(data.filters?.created_before);
  if (!createdAfter && !createdBefore) return {};

  const ctx = data.date_range_context;
  const context: DateRangeContext = {};
  if (ctx && typeof ctx === "object") {
    const from = nonEmptyString(ctx.from);
    const to = nonEmptyString(ctx.to);
    const timezone = nonEmptyString(ctx.timezone);
    if (from) context.from = from;
    if (to) context.to = to;
    if (timezone) context.timezone = timezone;
  }
  return {
    ...(createdAfter && { createdAfter }),
    ...(createdBefore && { createdBefore }),
    ...(Object.keys(context).length > 0 && { context }),
  };
}

/** Calendar days to show in the picker for a saved range, or null when unrestricted. */
export function displayRangeFromSaved(
  range: SavedDateRange | undefined,
): DateRangeValue | null {
  if (!range || !hasDateBounds(range)) return null;

  const from = range.context?.from
    ? parseCalendarDay(range.context.from)
    : null;
  const to = range.context?.to ? parseCalendarDay(range.context.to) : null;
  if (from || to) {
    return { ...(from && { from }), ...(to && { to }) };
  }

  // No usable context (e.g. a filter created through the API): derive the
  // days from the bounds in the viewer's timezone.
  const after = range.createdAfter ? new Date(range.createdAfter) : null;
  const before = range.createdBefore ? new Date(range.createdBefore) : null;
  const derivedFrom = after && !Number.isNaN(after.getTime()) ? after : null;
  const derivedTo = before && !Number.isNaN(before.getTime()) ? before : null;
  if (!derivedFrom && !derivedTo) return null;
  return {
    ...(derivedFrom && { from: derivedFrom }),
    ...(derivedTo && { to: derivedTo }),
  };
}

/** Bounds + display context for a range the user just picked (viewer's timezone). */
export function savedRangeFromSelection(
  range: DateRangeValue | null | undefined,
): SavedDateRange {
  if (!range?.from && !range?.to) return NO_DATE_RANGE;
  return {
    ...(range.from && {
      createdAfter: toLocalDayStartISOString(range.from),
    }),
    ...(range.to && { createdBefore: toLocalDayEndISOString(range.to) }),
    context: {
      ...(range.from && { from: toLocalDayKey(range.from) }),
      ...(range.to && { to: toLocalDayKey(range.to) }),
      timezone: viewerTimeZone(),
    },
  };
}

function dayKey(date: Date | undefined): string | undefined {
  return date ? toLocalDayKey(date) : undefined;
}

export function sameCalendarDays(
  a: DateRangeValue | null | undefined,
  b: DateRangeValue | null | undefined,
): boolean {
  return dayKey(a?.from) === dayKey(b?.from) && dayKey(a?.to) === dayKey(b?.to);
}

/**
 * Next saved range after the user picks `next` while `current` is in effect.
 * Re-picking the days already shown keeps `current` untouched, so applying an
 * unchanged range in another timezone never rewrites its saved bounds.
 */
export function applySelection(
  current: SavedDateRange,
  next: DateRangeValue | null | undefined,
): SavedDateRange {
  if (sameCalendarDays(displayRangeFromSaved(current), next)) return current;
  return savedRangeFromSelection(next);
}

/** Saved timezone worth surfacing: only when it differs from the viewer's. */
export function foreignTimeZone(
  range: SavedDateRange | undefined,
): string | null {
  const tz = range?.context?.timezone;
  return tz && hasDateBounds(range) && tz !== viewerTimeZone() ? tz : null;
}
