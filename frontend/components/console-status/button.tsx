"use client";

import { EvCharger } from "lucide-react";
import type { ComponentState } from "@/app/api/queries/useConsoleStatusQuery";
import { useNarrowLayout } from "@/hooks/use-narrow-layout";
import { statusTokens } from "@/lib/status-utils";
import { cn } from "@/lib/utils";

interface ConsoleStatusButtonProps {
  onClick: () => void;
  isOpen: boolean;
  overallStatus?: ComponentState;
}

export function ConsoleStatusButton({
  onClick,
  isOpen,
  overallStatus,
}: ConsoleStatusButtonProps) {
  const isNarrow = useNarrowLayout();

  return (
    <button
      type="button"
      id="console-status-trigger"
      onClick={onClick}
      aria-expanded={isOpen}
      aria-controls="console-status-panel"
      aria-haspopup="dialog"
      aria-label="Console Status"
      className={cn(
        "relative flex items-center gap-2 rounded-lg transition-colors",
        isNarrow
          ? "h-8 w-8 justify-center hover:bg-muted"
          : "px-3 py-2 bg-zinc-800 border border-zinc-700 text-zinc-200 text-sm font-medium hover:bg-zinc-700 hover:border-zinc-600 shadow-lg",
        !isNarrow && isOpen && "bg-zinc-700 border-zinc-500",
      )}
    >
      <EvCharger
        size={isNarrow ? 16 : 14}
        className={cn(
          "shrink-0",
          isNarrow ? "text-muted-foreground" : "text-zinc-400",
        )}
      />
      {!isNarrow && <span>Console Status</span>}
      {overallStatus &&
        (isNarrow ? (
          /* Narrow: top-right corner dot, matching the bell */
          <span className="absolute right-1 top-1 flex h-2 w-2">
            {overallStatus === "unhealthy" && (
              <span className="absolute inline-flex h-full w-full rounded-full bg-destructive opacity-75 animate-ping motion-reduce:hidden" />
            )}
            <span
              className={cn(
                "relative inline-flex h-2 w-2 rounded-full",
                statusTokens(overallStatus).dot,
              )}
            />
          </span>
        ) : (
          /* Wide: inline dot after the label */
          <span className="relative flex h-2 w-2 shrink-0">
            {overallStatus === "unhealthy" && (
              <span className="absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75 animate-ping motion-reduce:hidden" />
            )}
            <span
              className={cn(
                "relative inline-flex h-2 w-2 rounded-full",
                statusTokens(overallStatus).dot,
              )}
            />
          </span>
        ))}
    </button>
  );
}
