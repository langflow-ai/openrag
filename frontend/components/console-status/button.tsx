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
        "bg-zinc-800 border border-zinc-700 text-zinc-200 text-sm font-medium",
        "hover:bg-zinc-700 hover:border-zinc-600 transition-colors shadow-lg",
        isOpen && "bg-zinc-700 border-zinc-500",
      )}
    >
      <EvCharger size={14} className="shrink-0 text-zinc-400" />
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
