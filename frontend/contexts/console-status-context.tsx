"use client";

import type React from "react";
import {
  createContext,
  use,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import {
  type ComponentState,
  type ComponentStatus,
  type ConsoleStatusResponse,
  useConsoleStatusQuery,
} from "@/app/api/queries/useConsoleStatusQuery";
import { useAuth } from "@/contexts/auth-context";

/** Collapses the four component states into the two things the UI reacts to:
 *  a warning (amber) or an outage (red). `ok` means nothing to show. */
export type StatusSeverity = "ok" | "warn" | "down";

interface ConsoleStatusContextType {
  overallStatus: ComponentState | undefined;
  /** Components that are not healthy, sorted by name (stable order). Each of
   *  these becomes a "system event" in the notification bell menu. */
  problems: ComponentStatus[];
  severity: StatusSeverity;
  /** True when at least one component is degraded / unknown / down. Drives the
   *  notification-bell dot. */
  hasProblem: boolean;
  /** Query couldn't complete (e.g. auth) — treated as neutral, never a problem. */
  isError: boolean;
  isOpen: boolean;
  open: () => void;
  close: () => void;
  toggle: () => void;
}

const ConsoleStatusContext = createContext<
  ConsoleStatusContextType | undefined
>(undefined);

// ─── helpers ───────────────────────────────────────────────────────────────

function severityOf(status: ComponentState | undefined): StatusSeverity {
  switch (status) {
    case "unhealthy":
      return "down";
    case "degraded":
    case "unknown":
      return "warn";
    default:
      // "healthy" or no data yet
      return "ok";
  }
}

const SEVERITY_RANK: Record<StatusSeverity, number> = {
  ok: 0,
  warn: 1,
  down: 2,
};

function problemSummary(problems: ComponentStatus[]): string {
  if (problems.length === 0) return "A component needs attention.";
  if (problems.length === 1) {
    const p = problems[0];
    return `${p.display_name} is ${p.status}.`;
  }
  const names = problems.map((p) => p.display_name).join(", ");
  return `${problems.length} components need attention: ${names}.`;
}

// ─── provider ────────────────────────────────────────────────────────────────

export function ConsoleStatusProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { runMode } = useAuth();
  const isOss = runMode === "oss";

  // Shares the ["console-status"] cache key with the panel/button — React Query
  // dedupes, so mounting this provider does not add a second poll.
  // Disabled outside OSS so polling never fires in saas or on_prem.
  const { data, isError } = useConsoleStatusQuery({ enabled: isOss });

  const [isOpen, setIsOpen] = useState(false);

  const overallStatus = (data as ConsoleStatusResponse | undefined)
    ?.overall_status;

  const problems = useMemo(() => {
    const components = Array.isArray(data?.components) ? data.components : [];
    return components
      .filter((c) => c.status !== "healthy")
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [data]);

  const severity = severityOf(overallStatus);
  const hasProblem = severity !== "ok";

  const open = useCallback(() => setIsOpen(true), []);
  const close = useCallback(() => setIsOpen(false), []);
  const toggle = useCallback(() => setIsOpen((v) => !v), []);

  // Active push: one toast per healthy→bad / bad→worse transition. `prevRef`
  // starts undefined and is seeded on the first successful fetch so we never
  // toast on initial load or on a page refresh.
  const prevStatusRef = useRef<ComponentState | undefined>(undefined);
  useEffect(() => {
    if (!overallStatus) return;

    const prev = prevStatusRef.current;
    prevStatusRef.current = overallStatus;

    if (prev === undefined || prev === overallStatus) return;

    const prevSev = severityOf(prev);
    const nextSev = severityOf(overallStatus);

    if (SEVERITY_RANK[nextSev] > SEVERITY_RANK[prevSev]) {
      const message =
        nextSev === "down" ? "OpenRAG component down" : "OpenRAG degraded";
      const fire = nextSev === "down" ? toast.error : toast.warning;
      fire(message, {
        description: problemSummary(problems),
        action: { label: "View", onClick: () => open() },
      });
    } else if (nextSev === "ok") {
      toast.success("All systems healthy");
    }
  }, [overallStatus, problems, open]);

  const value: ConsoleStatusContextType = {
    overallStatus,
    problems,
    severity,
    hasProblem,
    isError,
    isOpen,
    open,
    close,
    toggle,
  };

  return (
    <ConsoleStatusContext.Provider value={value}>
      {children}
    </ConsoleStatusContext.Provider>
  );
}

// Safe default returned when the feature is disabled (non-OSS run modes).
// Consumers such as header.tsx and task-notification-menu.tsx receive
// hasProblem=false and no-op callbacks, keeping the UI inert.
const NOOP_STATUS: Readonly<ConsoleStatusContextType> = Object.freeze({
  overallStatus: undefined,
  problems: [],
  severity: "ok" as StatusSeverity,
  hasProblem: false,
  isError: false,
  isOpen: false,
  open: () => {},
  close: () => {},
  toggle: () => {},
});

export function useConsoleStatus(): ConsoleStatusContextType {
  return use(ConsoleStatusContext) ?? NOOP_STATUS;
}
