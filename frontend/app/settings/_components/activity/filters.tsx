"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** `datetime-local` text -> UTC ISO instant; empty -> undefined. */
export function localToUtcIso(value: string): string | undefined {
  if (!value) return undefined;
  const d = new Date(`${value}Z`); // the picker is treated as UTC, shown as such
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

export function formatUtc(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

export interface RangeDraft {
  start: string;
  end: string;
}

export function RangeInputs({
  value,
  onChange,
}: {
  value: RangeDraft;
  onChange: (next: RangeDraft) => void;
}) {
  return (
    <>
      <div className="flex flex-col gap-1">
        <Label htmlFor="activity-start">Start (UTC)</Label>
        <Input
          id="activity-start"
          type="datetime-local"
          value={value.start}
          onChange={(e) => onChange({ ...value, start: e.target.value })}
        />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="activity-end">End (UTC, exclusive)</Label>
        <Input
          id="activity-end"
          type="datetime-local"
          value={value.end}
          onChange={(e) => onChange({ ...value, end: e.target.value })}
        />
      </div>
    </>
  );
}
