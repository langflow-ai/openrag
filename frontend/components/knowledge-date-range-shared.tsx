"use client";

import { addDays, isSameDay, startOfDay } from "date-fns";
import { useEffect, useState } from "react";
import type { DateRange, DayContentProps } from "react-day-picker";
import { Calendar } from "@/components/ui/calendar";
import { cn } from "@/lib/utils";

/** Pieces shared by the classic and V2 date-range pickers. */

export function DensityMark({
  count,
  inverted,
}: {
  count: number;
  inverted: boolean;
}) {
  if (count <= 0) return <span aria-hidden className="h-1" />;
  return (
    <span
      aria-hidden
      data-testid="upload-density"
      data-density={count >= 5 ? "high" : count >= 2 ? "medium" : "low"}
      className={cn(
        "h-1 rounded-full",
        count >= 5 ? "w-5" : count >= 2 ? "w-3" : "w-1",
        inverted ? "bg-primary-foreground" : "bg-primary",
      )}
    />
  );
}

export function useToday(open: boolean) {
  // Refreshed while open so a page left running past midnight never keeps
  // yesterday as "today".
  const [today, setToday] = useState(() => startOfDay(new Date()));

  useEffect(() => {
    if (!open) return;
    const rollover = () => {
      const now = startOfDay(new Date());
      setToday((prev) => (isSameDay(prev, now) ? prev : now));
    };
    const nextMidnight = addDays(startOfDay(new Date()), 1);
    const timer = setTimeout(
      rollover,
      nextMidnight.getTime() - Date.now() + 1000,
    );
    return () => clearTimeout(timer);
  }, [open, today]);

  return [today, setToday] as const;
}

export function CalendarPanel({
  draft,
  month,
  today,
  DayContent,
  onSelect,
  onMonthChange,
}: {
  draft: DateRange | undefined;
  month: Date;
  today: Date;
  DayContent: (props: DayContentProps) => React.JSX.Element;
  onSelect: (next: DateRange | undefined) => void;
  onMonthChange: (month: Date) => void;
}) {
  return (
    <div className="flex flex-1 flex-col items-center px-1 py-3 sm:px-4">
      <Calendar
        mode="range"
        selected={draft}
        onSelect={onSelect}
        month={month}
        onMonthChange={onMonthChange}
        toMonth={today}
        disabled={{ after: today }}
        components={{ DayContent }}
        classNames={{
          caption_label: "text-base font-semibold",
          head_cell: "w-9 text-xs font-normal text-muted-foreground sm:w-14",
          cell: cn(
            "relative h-11 w-9 p-0 text-center text-sm sm:h-12 sm:w-14",
            "[&:has([aria-selected])]:bg-accent",
            "first:[&:has([aria-selected])]:rounded-l-md",
            "last:[&:has([aria-selected])]:rounded-r-md",
            "focus-within:relative focus-within:z-20",
          ),
          day: "inline-flex h-11 w-9 items-center justify-center rounded-md p-0 font-normal hover:bg-accent/70 aria-selected:opacity-100 sm:h-12 sm:w-14",
        }}
      />
      <div className="mt-2 flex w-full items-center gap-4 px-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="h-1 w-1 rounded-full bg-primary" />1 upload
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1 w-3 rounded-full bg-primary" />
          2–4
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1 w-5 rounded-full bg-primary" />
          5+
        </span>
      </div>
    </div>
  );
}
