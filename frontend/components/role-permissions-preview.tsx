"use client";

import { ChevronDown, Info } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

interface RolePermissionsPreviewProps {
  /** Role name (display only). */
  name: string;
  /** Optional description shown above the permissions list. */
  description?: string | null;
  /** Full permission set granted by this role. */
  permissions: string[];
  /** Optional trigger override. Defaults to a small info icon. */
  trigger?: React.ReactNode;
  /** Visual size of the trigger icon. */
  size?: "sm" | "md";
}

/**
 * Hover/click-to-open popover showing every permission a role grants.
 * Used inline next to a role badge or in the role-assign dropdown.
 */
export function RolePermissionsPreview({
  name,
  description,
  permissions,
  trigger,
  size = "sm",
}: RolePermissionsPreviewProps) {
  const [open, setOpen] = useState(false);

  // Group permissions by resource for readability:
  //   connectors:create / connectors:list:own / kf:create / ...
  const grouped = permissions.reduce<Record<string, string[]>>((acc, p) => {
    const [resource] = p.split(":");
    if (!acc[resource]) acc[resource] = [];
    acc[resource].push(p);
    return acc;
  }, {});

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {trigger ?? (
          <button
            type="button"
            aria-label={`Show permissions for ${name}`}
            className={cn(
              "inline-flex items-center justify-center rounded hover:bg-foreground/10 transition-colors -mr-0.5",
              size === "sm" ? "h-5 w-5" : "h-6 w-6",
            )}
          >
            <Info className={size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4"} />
          </button>
        )}
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="end" sideOffset={4}>
        <div className="px-3 pt-3 pb-2 border-b">
          <p className="text-sm font-medium leading-none capitalize">{name}</p>
          {description && (
            <p className="text-xs text-muted-foreground mt-1">{description}</p>
          )}
          <p className="text-xs text-muted-foreground mt-1.5">
            {permissions.length} permission{permissions.length === 1 ? "" : "s"}
          </p>
        </div>
        <ScrollArea className="max-h-72">
          <div className="px-3 py-2 space-y-3">
            {Object.entries(grouped)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([resource, perms]) => (
                <div key={resource}>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground mb-1">
                    {resource}
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {perms.sort().map((p) => (
                      <Badge
                        key={p}
                        variant="outline"
                        className="text-[10px] font-mono py-0 px-1.5 leading-4"
                      >
                        {p.split(":").slice(1).join(":")}
                      </Badge>
                    ))}
                  </div>
                </div>
              ))}
          </div>
        </ScrollArea>
      </PopoverContent>
    </Popover>
  );
}
