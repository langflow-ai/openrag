"use client";

import { isAfter, isSameDay, startOfDay, subDays } from "date-fns";
import { CalendarIcon, Check, ChevronDown } from "lucide-react";
import { useRef, useState } from "react";
import type { Matcher } from "react-day-picker";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  type DateRangeValue,
  describeRange,
  viewerTimeZone,
} from "@/lib/saved-date-range";
import { cn } from "@/lib/utils";

const PRESET_DAYS = [30, 60, 90] as const;
const DEFAULT_CUSTOM_DAYS = 30;

type Field = "from" | "to";

function formatFieldDate(date: Date | undefined): string {
  return date
    ? date.toLocaleDateString(undefined, {
        month: "2-digit",
        day: "2-digit",
        year: "2-digit",
      })
    : "Select date";
}

type OptionId = "all" | `${number}` | "custom";

function activeOption(draft: DateRangeValue | null, today: Date): OptionId {
  if (!draft?.from && !draft?.to) return "all";
  const preset = PRESET_DAYS.find(
    (n) =>
      draft.from &&
      draft.to &&
      isSameDay(draft.to, today) &&
      isSameDay(draft.from, subDays(today, n - 1)),
  );
  return preset ? (String(preset) as OptionId) : "custom";
}

export interface KnowledgeFilterDateFieldProps {
  value: DateRangeValue | null;
  onChange: (range: DateRangeValue | null) => void;
  /** Timezone the shown days were saved in, when it differs from the viewer's. */
  savedTimeZone?: string | null;
}

/**
 * "Date ingested" control for the Knowledge Filter editor: a short list of
 * ranges plus From/To fields that open a single-day calendar. It edits only
 * an unsaved draft; the filter's own Save decides what is persisted.
 */
export function KnowledgeFilterDateField({
  value,
  onChange,
  savedTimeZone = null,
}: KnowledgeFilterDateFieldProps) {
  const [open, setOpen] = useState(false);
  const [today, setToday] = useState(() => startOfDay(new Date()));
  const [draft, setDraft] = useState<DateRangeValue | null>(value);
  const [expanded, setExpanded] = useState<Field | null>(null);
  // False until the user changes the draft; Apply then keeps the range as saved.
  const edited = useRef(false);

  const handleOpenChange = (next: boolean) => {
    if (next) {
      setToday(startOfDay(new Date()));
      setDraft(value);
      setExpanded(null);
      edited.current = false;
    }
    setOpen(next);
  };

  const update = (next: DateRangeValue | null) => {
    edited.current = true;
    setDraft(next);
  };

  const active = activeOption(draft, today);

  const options: { id: OptionId; label: string; select: () => void }[] = [
    {
      id: "all",
      label: "All dates",
      select: () => {
        update(null);
        setExpanded(null);
      },
    },
    ...PRESET_DAYS.map((n) => ({
      id: String(n) as OptionId,
      label: `Last ${n} days`,
      select: () => {
        update({ from: subDays(today, n - 1), to: today });
        setExpanded(null);
      },
    })),
    {
      id: "custom",
      label: "Custom date range",
      select: () => {
        if (!draft?.from && !draft?.to) {
          update({
            from: subDays(today, DEFAULT_CUSTOM_DAYS - 1),
            to: today,
          });
        }
        setExpanded("from");
      },
    },
  ];

  const pick = (field: Field, date: Date) => {
    if (field === "from") {
      // A start after the current end drags the end along, never inverts the range.
      update({
        from: date,
        to: draft?.to && isAfter(date, draft.to) ? date : draft?.to,
      });
    } else {
      update({ from: draft?.from, to: date });
    }
    setExpanded(null);
  };

  const disabledDays = (field: Field): Matcher[] => {
    const matchers: Matcher[] = [{ after: today }];
    if (field === "to" && draft?.from) {
      matchers.push({ before: draft.from });
    }
    return matchers;
  };

  const apply = () => {
    if (edited.current) onChange(draft?.from || draft?.to ? draft : null);
    setOpen(false);
  };

  const label = describeRange(value);
  const fields: { field: Field; title: string; day: Date | undefined }[] = [
    { field: "from", title: "From", day: draft?.from },
    { field: "to", title: "To", day: draft?.to },
  ];

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className="h-auto min-h-9 w-full justify-start gap-2 px-3 text-sm font-normal"
          aria-label={label ?? "Filter by date ingested"}
        >
          <CalendarIcon className="h-4 w-4 flex-shrink-0 text-[var(--icon-primary)]" />
          <span className="truncate">{label ?? "All dates"}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="max-h-[80vh] w-[min(24rem,calc(100vw-2rem))] overflow-y-auto p-0"
        align="start"
        collisionPadding={16}
      >
        <div className="flex flex-col p-2" role="group" aria-label="Date range">
          {options.map((option) => (
            <button
              key={option.id}
              type="button"
              aria-pressed={option.id === active}
              onClick={option.select}
              className={cn(
                "flex items-center justify-between rounded-md px-3 py-3 text-left text-sm transition-colors hover:bg-accent",
                option.id === active && "bg-accent font-medium",
              )}
            >
              <span>{option.label}</span>
              {option.id === active && (
                <Check className="h-4 w-4" aria-hidden />
              )}
            </button>
          ))}
        </div>

        <div className="flex flex-col gap-3 border-t px-4 py-4">
          {fields.map(({ field, title, day }) => {
            const isOpen = expanded === field;
            return (
              <div key={field} className="flex flex-col gap-1.5">
                <span className="text-xs text-muted-foreground">{title}</span>
                <button
                  type="button"
                  aria-label={`${title} date`}
                  aria-expanded={isOpen}
                  onClick={() => setExpanded(isOpen ? null : field)}
                  className="flex h-11 w-full items-center gap-3 rounded-full border bg-background px-4 text-sm"
                >
                  <CalendarIcon className="h-4 w-4 flex-shrink-0" aria-hidden />
                  <span
                    className={cn(
                      "flex-1 text-left",
                      !day && "text-muted-foreground",
                    )}
                  >
                    {formatFieldDate(day)}
                  </span>
                  <ChevronDown
                    className={cn(
                      "h-4 w-4 transition-transform",
                      isOpen && "rotate-180",
                    )}
                    aria-hidden
                  />
                </button>
                {isOpen && (
                  <div className="flex justify-center">
                    <Calendar
                      mode="single"
                      selected={day}
                      defaultMonth={day ?? today}
                      toMonth={today}
                      disabled={disabledDays(field)}
                      onSelect={(date) => date && pick(field, date)}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {savedTimeZone && (
          <p className="border-t px-4 py-2 text-xs text-muted-foreground">
            Saved in {savedTimeZone}. Days you pick here use your time zone (
            {viewerTimeZone()}).
          </p>
        )}

        <div className="flex justify-end gap-2 border-t p-3">
          <Button
            type="button"
            variant="outline"
            ignoreTitleCase
            onClick={() => setOpen(false)}
          >
            Cancel
          </Button>
          <Button type="button" ignoreTitleCase onClick={apply}>
            Apply
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
