"use client";

import React, { type SVGProps } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  File,
  Book,
  Scroll,
  Library,
  Map,
  FileImage,
  Layers3,
  Database,
  Folder,
  Archive,
  MessagesSquare,
  SquareStack,
  Ghost,
  Gem,
  Swords,
  Bolt,
  Shield,
  Hammer,
  Globe,
  HardDrive,
  Upload,
  Cable,
  ShoppingCart,
  ShoppingBag,
  Check,
  Plus,
} from "lucide-react";
import { filterAccentClasses } from "./knowledge-filter-panel";
import { cn } from "@/lib/utils";

const ICON_MAP = {
  file: File,
  book: Book,
  scroll: Scroll,
  library: Library,
  map: Map,
  image: FileImage,
  layers3: Layers3,
  database: Database,
  folder: Folder,
  archive: Archive,
  messagesSquare: MessagesSquare,
  squareStack: SquareStack,
  ghost: Ghost,
  gem: Gem,
  swords: Swords,
  bolt: Bolt,
  shield: Shield,
  hammer: Hammer,
  globe: Globe,
  hardDrive: HardDrive,
  upload: Upload,
  cable: Cable,
  shoppingCart: ShoppingCart,
  shoppingBag: ShoppingBag,
} as const;

export type IconKey = keyof typeof ICON_MAP;

export function iconKeyToComponent(
  key?: string
): React.ComponentType<SVGProps<SVGSVGElement>> | undefined {
  if (!key) return undefined;
  return (
    ICON_MAP as Record<string, React.ComponentType<SVGProps<SVGSVGElement>>>
  )[key];
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
  zinc: "bg-muted-foreground text-accent-foreground",
  pink: "bg-accent-pink-foreground text-accent-pink",
  purple: "bg-accent-purple-foreground text-accent-purple",
  indigo: "bg-accent-indigo-foreground text-accent-indigo",
  emerald: "bg-accent-emerald-foreground text-accent-emerald",
  amber: "bg-accent-amber-foreground text-accent-amber",
  red: "bg-accent-red-foreground text-accent-red",
  "": "bg-muted-foreground text-accent-foreground",
};

export interface FilterIconPopoverProps {
  color: FilterColor;
  iconKey?: IconKey | undefined;
  onColorChange: (c: FilterColor) => void;
  onIconChange: (k: IconKey | undefined) => void;
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
        <button
          className={cn(
            "h-10 w-10 min-w-10 min-h-10 rounded-sm flex items-center justify-center transition-colors",
            filterAccentClasses[color || ""],
            triggerClassName
          )}
        >
          {Icon && <Icon className="h-5 w-5" />}
          {!Icon && <Plus className="h-5 w-5" />}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80" align="start">
        <div className="space-y-4">
          <div className="grid grid-cols-7 items-center gap-2">
            {COLORS.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => onColorChange(c)}
                className={cn(
                  "flex items-center justify-center h-6 w-6 rounded-sm transition-colors",
                  colorSwatchClasses[c || ""]
                )}
                aria-label={c}
              >
                {c === color && <Check className="h-3.5 w-3.5" />}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-6 gap-2">
            {Object.keys(ICON_MAP).map((k: string) => {
              const OptIcon = ICON_MAP[k as IconKey];
              const active = iconKey === k;
              return (
                <button
                  key={k}
                  type="button"
                  onClick={() => {
                    if (active) {
                      onIconChange(undefined);
                    } else {
                      onIconChange(k as IconKey);
                    }
                  }}
                  className={
                    "h-8 w-8 inline-flex items-center hover:text-foreground justify-center rounded border " +
                    (active
                      ? "border-muted-foreground text-foreground"
                      : "border-0 text-muted-foreground")
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
