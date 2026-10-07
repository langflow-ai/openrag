"use client";

import { CalendarIcon, X } from "lucide-react";
import { useState } from "react";
import type { DateRange } from "react-day-picker";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { cn } from "@/lib/utils";

function formatDateLabel(date: Date): string {
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function KnowledgeDateRangeFilter() {
  const { dateRange, setDateRange } = useKnowledgeFilter();
  const [open, setOpen] = useState(false);
  // Captured once on mount so server/client renders agree on the same Date.
  const [today] = useState(() => new Date());

  const selectedRange: DateRange | undefined = dateRange
    ? { from: dateRange.from, to: dateRange.to }
    : undefined;

  const handleSelect = (range: DateRange | undefined) => {
    setDateRange(range ? { from: range.from, to: range.to } : null);
    if (range?.from && range?.to) {
      setOpen(false);
    }
  };

  const handlePreset = (days: number) => {
    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - days + 1);
    setDateRange({ from, to });
    setOpen(false);
  };

  const handleThisMonth = () => {
    const now = new Date();
    const from = new Date(now.getFullYear(), now.getMonth(), 1);
    setDateRange({ from, to: now });
    setOpen(false);
  };

  const handleClear = () => {
    setDateRange(null);
    setOpen(false);
  };

  const label = dateRange?.from
    ? dateRange.to
      ? `${formatDateLabel(dateRange.from)} – ${formatDateLabel(dateRange.to)}`
      : formatDateLabel(dateRange.from)
    : null;

  return (
    <div className="flex-shrink-0 flex items-center gap-0.5">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant={dateRange ? "secondary" : "outline"}
            className={cn("rounded-lg gap-2", dateRange && "border-primary/50")}
            aria-label={label ?? "Filter by date range"}
          >
            <CalendarIcon className="h-4 w-4" />
            {label ? (
              <span className="hidden sm:inline text-sm">{label}</span>
            ) : (
              <span className="hidden sm:inline text-sm">Date range</span>
            )}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <div className="flex gap-1 p-2 border-b">
            <Button
              variant="ghost"
              size="sm"
              className="text-xs"
              onClick={() => handlePreset(7)}
            >
              Last 7 days
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-xs"
              onClick={() => handlePreset(30)}
            >
              Last 30 days
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-xs"
              onClick={handleThisMonth}
            >
              This month
            </Button>
          </div>
          <Calendar
            mode="range"
            selected={selectedRange}
            onSelect={handleSelect}
            numberOfMonths={2}
            defaultMonth={dateRange?.from ?? today}
            disabled={{ after: today }}
          />
          {dateRange && (
            <div className="border-t p-2 flex justify-end">
              <Button variant="ghost" size="sm" onClick={handleClear}>
                Clear
              </Button>
            </div>
          )}
        </PopoverContent>
      </Popover>
      {dateRange && (
        <button
          type="button"
          aria-label="Clear date range"
          className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-muted text-muted-foreground"
          onClick={handleClear}
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}
