import AnimatedProcessingIcon from "../icons/animated-processing-icon";

export type Status =
  | "processing"
  | "active"
  | "unavailable"
  | "hidden"
  | "sync"
  | "failed"
  | "cancelled"
  | "ready"
  | "fallback"
  | "not-configured"
  | "skipped";

interface StatusBadgeProps {
  /**
   * A known status, or any other string an API response can carry. Callers
   * read this straight off a file or task record, so the set is not ours to
   * close — `Status` exists for autocomplete, not as a guarantee.
   */
  status: Status | (string & {});
  className?: string;
}

const statusConfig = {
  processing: {
    label: "Processing",
    className: "text-muted-foreground ",
  },
  active: {
    label: "Active",
    className: "text-accent-emerald-foreground ",
  },
  unavailable: {
    label: "Unavailable",
    className: "text-accent-red-foreground ",
  },
  failed: {
    label: "Failed",
    className: "text-accent-red-foreground ",
  },
  cancelled: {
    label: "Cancelled",
    className: "text-muted-foreground ",
  },
  hidden: {
    label: "Hidden",
    className: "text-muted-foreground ",
  },
  sync: {
    label: "Sync",
    className: "text-accent-amber-foreground underline",
  },
  ready: {
    label: "Ready",
    className: "text-accent-emerald-foreground ",
  },
  fallback: {
    label: "Using environment default",
    className: "text-accent-amber-foreground ",
  },
  "not-configured": {
    label: "Not configured",
    className: "text-muted-foreground ",
  },
  skipped: {
    label: "Skipped",
    className: "text-muted-foreground ",
  },
};

/** Title-cases a status this badge has no entry for: "in_progress" → "In progress". */
function labelForUnknownStatus(status: string): string {
  const spaced = status.replace(/[_-]+/g, " ").trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : "Unknown";
}

export const StatusBadge = ({ status, className }: StatusBadgeProps) => {
  // A status with no entry here renders as its own name rather than throwing.
  // This read used to be `statusConfig[status].className`, which took the whole
  // page down through the error boundary the first time a file arrived as
  // "skipped" — a presentational badge is never a good reason to lose the view
  // it sits in, and the set of statuses the API can send is not fixed.
  const config = statusConfig[status as Status] as
    | { label: string; className: string }
    | undefined;
  const label = config?.label ?? labelForUnknownStatus(status);
  const statusClassName = config?.className ?? "text-muted-foreground ";

  return (
    <div
      className={`inline-flex items-center gap-1 ${statusClassName} ${
        className || ""
      }`}
    >
      {status === "processing" && (
        <AnimatedProcessingIcon className="text-current shrink-0" />
      )}
      {label}
    </div>
  );
};
