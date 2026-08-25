"use client";

import type { ComponentState } from "@/app/api/queries/useConsoleStatusQuery";
import { statusTokens } from "@/lib/status-utils";
import { cn } from "@/lib/utils";

export function StatusIcon({
  status,
  size = 16,
}: {
  status: ComponentState;
  size?: number;
}) {
  const { Icon, text } = statusTokens(status);
  return <Icon size={size} className={cn(text, "shrink-0")} />;
}
