import {
  AlertTriangle,
  CheckCircle2,
  HelpCircle,
  type LucideIcon,
  XCircle,
} from "lucide-react";

export interface StatusTokens {
  text: string;
  badge: string;
  dot: string;
  Icon: LucideIcon;
}

export function statusTokens(status: string): StatusTokens {
  switch (status) {
    case "healthy":
      return {
        text: "text-emerald-400",
        badge: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
        dot: "bg-emerald-400",
        Icon: CheckCircle2,
      };
    case "degraded":
      return {
        text: "text-amber-400",
        badge: "bg-amber-500/15 text-amber-400 border-amber-500/30",
        dot: "bg-amber-400",
        Icon: AlertTriangle,
      };
    case "unhealthy":
      return {
        text: "text-red-400",
        badge: "bg-red-500/15 text-red-400 border-red-500/30",
        dot: "bg-red-400",
        Icon: XCircle,
      };
    default:
      // "unknown"
      return {
        text: "text-zinc-400",
        badge: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
        dot: "bg-zinc-400",
        Icon: HelpCircle,
      };
  }
}

export function getApiError(body: unknown, status: number): string {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (typeof b.detail === "string") return b.detail;
    if (typeof b.error === "string") return b.error;
  }
  return `HTTP ${status}`;
}
/** Converts any supported timestamp format to a Date.
 *  Handles ISO-8601 strings, Unix epoch integers (s or ms), and Unix floats. */
function parseDate(value: string): Date {
  // Pure integer — Unix seconds (<= 10 digits) or milliseconds (> 10 digits)
  if (/^\d+$/.test(value)) {
    const n = parseInt(value, 10);
    return new Date(n < 10_000_000_000 ? n * 1000 : n);
  }
  // Float — Unix seconds with fractional component
  if (/^\d+\.\d+$/.test(value)) {
    return new Date(parseFloat(value) * 1000);
  }
  // ISO-8601 or any other format Date can parse
  return new Date(value);
}

/** "just now" / "45s ago" / "5m ago" / "2h ago" / "3d ago" from any timestamp.
 *  Accepts ISO-8601 strings, Unix epoch integers, or Unix float seconds.
 *  Returns "—" for null/undefined and "Unknown time" for unparseable input. */
export function formatRelative(value?: string | null): string {
  if (!value) return "—";
  const date = parseDate(value);
  if (Number.isNaN(date.getTime())) return "Unknown time";

  const diffMs = Date.now() - date.getTime();
  const secs = Math.round(diffMs / 1000);
  if (secs < 45) return "just now";

  const mins = Math.floor(diffMs / 60_000);
  // 45–59s (and round-to-60s while still under 1 minute) would otherwise be "0m ago".
  if (mins < 1) return `${secs}s ago`;
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(diffMs / 3_600_000);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(diffMs / 86_400_000);
  return `${days}d ago`;
}
