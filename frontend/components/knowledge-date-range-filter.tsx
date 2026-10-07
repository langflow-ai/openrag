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
    const to = new Date(now.getFullYear(), now.getMonth() + 1, 0);
    setDateRange({ from, to });
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
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant={dateRange ? "secondary" : "outline"}
          className={cn(
            "flex-shrink-0 rounded-lg gap-2",
            dateRange && "border-primary/50",
          )}
          aria-label={label ?? "Filter by date range"}
        >
          <CalendarIcon className="h-4 w-4" />
          {label ? (
            <span className="hidden sm:inline text-sm">{label}</span>
          ) : (
            <span className="hidden sm:inline text-sm">Date range</span>
          )}
          {dateRange && (
            <span
              role="button"
              tabIndex={0}
              aria-label="Clear date range"
              className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full hover:bg-muted"
              onClick={(e) => {
                e.stopPropagation();
                handleClear();
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.stopPropagation();
                  handleClear();
                }
              }}
            >
              <X className="h-3 w-3" />
            </span>
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
          defaultMonth={dateRange?.from ?? new Date()}
          disabled={{ after: new Date() }}
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
  );
}
