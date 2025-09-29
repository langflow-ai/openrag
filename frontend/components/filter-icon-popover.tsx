"use client";

import React, { type SVGProps } from "react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Filter as FilterIcon,
  Star,
  Book,
  FileText,
  Folder,
  Globe,
  Calendar,
  User,
  Users,
  Tag,
  Briefcase,
  Building2,
  Cog,
  Database,
  Cpu,
  Bot,
  MessageSquare,
  Search,
  Shield,
  Lock,
  Key,
  Link,
  Mail,
  Phone,
  Check,
} from "lucide-react";
import { filterAccentClasses } from "./knowledge-filter-panel";

const ICON_MAP = {
  Filter: FilterIcon,
  Star,
  Book,
  FileText,
  Folder,
  Globe,
  Calendar,
  User,
  Users,
  Tag,
  Briefcase,
  Building2,
  Cog,
  Database,
  Cpu,
  Bot,
  MessageSquare,
  Search,
  Shield,
  Lock,
  Key,
  Link,
  Mail,
  Phone,
} as const;

export type IconKey = keyof typeof ICON_MAP;

function iconKeyToComponent(
  key: string
): React.ComponentType<SVGProps<SVGSVGElement>> {
  return (
    (ICON_MAP as Record<string, React.ComponentType<SVGProps<SVGSVGElement>>>)[
      key
    ] || FilterIcon
  );
}

const COLORS = [
  "zinc",
  "pink",
  "purple",
  "indigo",
  "emerald",
  "amber",
  "red",
] as const;
export type FilterColor = (typeof COLORS)[number];

const colorSwatchClasses = {
  zinc: "bg-muted-foreground",
  pink: "bg-accent-pink-foreground",
  purple: "bg-accent-purple-foreground",
  indigo: "bg-accent-indigo-foreground",
  emerald: "bg-accent-emerald-foreground",
  amber: "bg-accent-amber-foreground",
  red: "bg-accent-red-foreground",
  "": "bg-muted-foreground",
};

export interface FilterIconPopoverProps {
  color: FilterColor;
  iconKey: IconKey | string;
  onColorChange: (c: FilterColor) => void;
  onIconChange: (k: IconKey) => void;
  triggerClassName?: string;
}

export function FilterIconPopover({
  color,
  iconKey,
  onColorChange,
  onIconChange,
  triggerClassName,
}: FilterIconPopoverProps) {
  const Icon = iconKeyToComponent(iconKey);
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="icon"
          className={"h-8 w-8 p-0 " + (triggerClassName || "")}
        >
          <span
            className={
              filterAccentClasses[color || ""] +
              " inline-flex items-center justify-center rounded h-6 w-6"
            }
          >
            <Icon className="h-3.5 w-3.5" />
          </span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80" align="start">
        <div className="space-y-3">
          <div className="grid grid-cols-7 items-center gap-2">
            {COLORS.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => onColorChange(c)}
                className={
                    
                  "flex items-center justify-center h-6 w-6 rounded-sm transition-colors " +
                  colorSwatchClasses[c || ""]
                }
                aria-label={c}
              >
                {c === color && <Check className="h-3.5 w-3.5" />}
              </button>
            ))}
          </div>
          <div className="text-xs font-medium text-muted-foreground mt-2">
            Icon
          </div>
          <div className="grid grid-cols-6 gap-2">
            {(Object.keys(ICON_MAP) as IconKey[]).map((k) => {
              const OptIcon = ICON_MAP[k];
              const active = iconKey === k;
              return (
                <button
                  key={k}
                  type="button"
                  onClick={() => onIconChange(k)}
                  className={
                    "h-8 w-8 inline-flex items-center justify-center rounded border " +
                    (active ? "border-foreground" : "border-border")
                  }
                  aria-label={k}
                >
                  <OptIcon className="h-4 w-4" />
                </button>
              );
            })}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
