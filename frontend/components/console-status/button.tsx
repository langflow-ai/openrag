"use client";

import { EvCharger } from "lucide-react";
import type { ComponentState } from "@/app/api/queries/useConsoleStatusQuery";
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
  return (
    <button
      type="button"
      id="console-status-trigger"
      onClick={onClick}
      aria-expanded={isOpen}
      aria-controls="console-status-panel"
      aria-haspopup="dialog"
      className={cn(
        "flex items-center gap-2 px-3 py-2 rounded-lg",
        "bg-muted border border-border text-foreground text-sm font-medium",
        "hover:bg-muted/80 hover:border-muted-foreground/40 transition-colors shadow-sm",
        isOpen && "bg-muted/80 border-muted-foreground/40",
      )}
    >
      <EvCharger size={14} className="shrink-0 text-muted-foreground" />
      <span>Console Status</span>
      {overallStatus && (
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
      )}
    </button>
  );
}
