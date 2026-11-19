"use client";

import { useState } from "react";
import {
  type FeedbackFilters,
  useFeedbackListQuery,
  useFeedbackSummaryQuery,
} from "@/app/api/queries/useActivityQueries";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { formatUtc, localToUtcIso, RangeInputs } from "./filters";

export function FeedbackPanel() {
  const [range, setRange] = useState({ start: "", end: "" });
  const [rating, setRating] = useState<"" | "up" | "down">("");

  const filters: FeedbackFilters = {
    start: localToUtcIso(range.start),
    end: localToUtcIso(range.end),
    rating: rating || undefined,
  };
  const summary = useFeedbackSummaryQuery(filters);
  const list = useFeedbackListQuery(filters);
  const items = list.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <section aria-label="Feedback" className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Feedback satisfaction: share of thumbs-up among votes. This is not an
        answer-accuracy score or a response rate.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <RangeInputs value={range} onChange={setRange} />
        <div className="flex flex-col gap-1">
          <Label htmlFor="activity-rating">Rating</Label>
          <select
            id="activity-rating"
            className="h-10 rounded-md border bg-background px-2 text-sm"
            value={rating}
            onChange={(e) => setRating(e.target.value as "" | "up" | "down")}
          >
            <option value="">All</option>
            <option value="up">Thumbs up</option>
            <option value="down">Thumbs down</option>
          </select>
        </div>
      </div>

      {summary.isError ? (
        <div role="alert" className="text-sm text-destructive">
          {summary.error.message}{" "}
          <Button variant="link" size="sm" onClick={() => summary.refetch()}>
            Retry summary
          </Button>
        </div>
      ) : summary.data ? (
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Thumbs up" value={summary.data.up} />
          <Stat label="Thumbs down" value={summary.data.down} />
          <Stat label="Total votes" value={summary.data.total} />
          <Stat
            label="Positive"
            value={
              summary.data.positive_percentage === null
                ? "—"
                : `${summary.data.positive_percentage}%`
            }
          />
        </dl>
      ) : (
        <p className="text-sm text-muted-foreground">Loading summary…</p>
      )}

      {list.isPending ? (
        <p className="text-sm text-muted-foreground">Loading feedback…</p>
      ) : list.isError && items.length === 0 ? (
        <div role="alert" className="text-sm text-destructive">
          {list.error.message}{" "}
          <Button variant="link" size="sm" onClick={() => list.refetch()}>
            Retry
          </Button>
        </div>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No feedback matches these filters.
        </p>
      ) : (
        <ul className="divide-y rounded-md border">
          {items.map((item) => (
            <li key={item.id} className="space-y-1 p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">
                  {item.rating === "up" ? "Thumbs up" : "Thumbs down"}
                </span>
                <time dateTime={item.created_at} className="text-xs">
                  {formatUtc(item.created_at)}
                </time>
                {item.model && (
                  <span className="text-xs text-muted-foreground">
                    {item.model_provider ? `${item.model_provider} / ` : ""}
                    {item.model}
                  </span>
                )}
              </div>
              {/* Rendered as plain text: React escapes it. */}
              {item.comment && (
                <p className="whitespace-pre-wrap">{item.comment}</p>
              )}
            </li>
          ))}
        </ul>
      )}
      {/* Loaded rows stay on screen. Retry the operation that actually failed:
          a failed "load more" re-requests the next page, while a failed
          background refresh re-requests the pages already shown. */}
      {list.isError && items.length > 0 && (
        <div role="alert" className="text-sm text-destructive">
          {list.error.message}{" "}
          {list.isFetchNextPageError ? (
            <Button
              variant="link"
              size="sm"
              onClick={() => list.fetchNextPage()}
            >
              Retry loading more
            </Button>
          ) : (
            <Button variant="link" size="sm" onClick={() => list.refetch()}>
              Retry refresh
            </Button>
          )}
        </div>
      )}
      {list.hasNextPage && !list.isError && (
        <Button
          variant="outline"
          size="sm"
          disabled={list.isFetchingNextPage}
          onClick={() => list.fetchNextPage()}
        >
          {list.isFetchingNextPage ? "Loading…" : "Load more"}
        </Button>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-xl font-semibold">{value}</dd>
    </div>
  );
}
