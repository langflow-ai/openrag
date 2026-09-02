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
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useTask } from "@/contexts/task-context";

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
  const { runMode, isAuthenticated, isNoAuthMode } = useAuth();
  const isOss = runMode === "oss";
  // Same gate as the panel: OSS + a session that can call /api/status.
  // run_mode is known on /login before a cookie exists; polling then would 401.
  const canFetchStatus = isOss && (isAuthenticated || isNoAuthMode);

  // Shares the ["console-status"] cache key with the panel — React Query
  // dedupes, so mounting this provider does not add a second poll.
  const { data, isError } = useConsoleStatusQuery({ enabled: canFetchStatus });
  const { closeMenu, isMenuOpen } = useTask();

  const [isOpen, setIsOpen] = useState(false);
  const isOpenRef = useRef(false);
  isOpenRef.current = isOpen;

  // Toast "View" and task-failure auto-open set the menu from TaskProvider
  // (a parent), so they cannot go through useOpenTaskMenu. Close whenever
  // the menu is open so the non-modal overlay cannot cover the task panel.
  useEffect(() => {
    if (isMenuOpen) setIsOpen(false);
  }, [isMenuOpen]);

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

  const open = useCallback(() => {
    closeMenu();
    setIsOpen(true);
  }, [closeMenu]);
  const close = useCallback(() => setIsOpen(false), []);
  const toggle = useCallback(() => {
    if (!isOpenRef.current) closeMenu();
    setIsOpen((v) => !v);
  }, [closeMenu]);

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
        nextSev === "down" ? "BomaRAG component down" : "BomaRAG degraded";
      const fire = nextSev === "down" ? toast.error : toast.warning;
      fire(message, {
        description: problemSummary(problems),
        action: { label: "View", onClick: () => open() },
      });
    } else if (nextSev === "ok") {
      toast.success("All systems healthy");
    }
  }, [overallStatus, problems, open]);

  // Memoize the bag, not the status: overallStatus / problems / hasProblem stay
  // in the dep list so a poll still re-renders the header and bell immediately.
  const value = useMemo<ConsoleStatusContextType>(
    () => ({
      overallStatus,
      problems,
      severity,
      hasProblem,
      isError,
      isOpen,
      open,
      close,
      toggle,
    }),
    [
      overallStatus,
      problems,
      severity,
      hasProblem,
      isError,
      isOpen,
      open,
      close,
      toggle,
    ],
  );

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

/** Open the task notification menu after closing Console Status and the
 *  knowledge filter so only one overlay is visible. */
export function useOpenTaskMenu() {
  const { openMenu } = useTask();
  const { close } = useConsoleStatus();
  const { closePanelOnly } = useKnowledgeFilter();
  return useCallback(() => {
    close();
    closePanelOnly();
    openMenu();
  }, [close, closePanelOnly, openMenu]);
}

export function useToggleTaskMenu() {
  const { toggleMenu, isMenuOpen } = useTask();
  const openTaskMenu = useOpenTaskMenu();
  return useCallback(() => {
    if (isMenuOpen) {
      toggleMenu();
    } else {
      openTaskMenu();
    }
  }, [isMenuOpen, toggleMenu, openTaskMenu]);
}
