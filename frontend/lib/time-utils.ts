export function parseTimestamp(value: string): Date | null {
  // Unix timestamp as integer string (seconds or milliseconds)
  if (/^\d+$/.test(value)) {
    const raw = Number.parseInt(value, 10);
    const millis = raw < 10_000_000_000 ? raw * 1000 : raw;
    const date = new Date(millis);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  // Unix timestamp with decimals (seconds)
  if (/^\d+\.\d+$/.test(value)) {
    const raw = Number.parseFloat(value);
    const date = new Date(raw * 1000);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function parseTimestampMs(value: string): number | null {
  const parsed = parseTimestamp(value);
  return parsed ? parsed.getTime() : null;
}

function formatClockTime(date: Date): string {
  return date
    .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    .toLowerCase();
}

function formatRelativeTime(date: Date, nowMs: number): string {
  const diffMs = nowMs - date.getTime();
  const diffSeconds = Math.floor(diffMs / 1000);
  const diffMinutes = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);

  if (diffSeconds <= 0) return "Just now";
  if (diffSeconds < 60) return `${diffSeconds}s ago`;
  if (diffMinutes < 60) return `${diffMinutes} min ago`;
  if (diffHours < 24) return `${diffHours} hours ago`;
  return `${Math.floor(diffHours / 24)} days ago`;
}

export function formatTaskTimestamp(
  date: Date | null,
  mode: "recent" | "past",
  nowMs: number,
): string {
  if (!date) return "Unknown time";
  if (mode === "recent") return formatRelativeTime(date, nowMs);

  const diffMs = nowMs - date.getTime();
  const diffSeconds = Math.floor(diffMs / 1000);
  const diffMinutes = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);

  // Past section should never show "Just now".
  if (diffSeconds < 60) return `${diffSeconds}s ago · ${formatClockTime(date)}`;
  if (diffMinutes < 60) {
    return `${diffMinutes} min ago · ${formatClockTime(date)}`;
  }
  if (diffHours < 24)
    return `${diffHours} hours ago · ${formatClockTime(date)}`;
  return `${Math.floor(diffHours / 24)} days ago · ${formatClockTime(date)}`;
}

// Day bounds are the viewer's local calendar day, sent as UTC instants. The
// "Date Uploaded" column renders indexed_time in local time too, so a file
// listed under a day is the file that day's filter returns, in any timezone.
export function toLocalDayStartISOString(date: Date): string {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

export function toLocalDayEndISOString(date: Date): string {
  const d = new Date(date);
  d.setHours(23, 59, 59, 999);
  // The backend stores microsecond-precision timestamps; extend the inclusive
  // bound through the day's final microsecond.
  return d.toISOString().replace(/\.999Z$/, ".999999Z");
}

// Matches the yyyy-MM-dd keys the upload histogram buckets by (viewer's time zone).
export function toLocalDayKey(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}
