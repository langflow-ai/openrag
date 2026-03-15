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

export function formatClockTime(date: Date): string {
  return date
    .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    .toLowerCase();
}

export function formatRelativeTime(date: Date, nowMs: number): string {
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
