import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/auth-context";
import { apiClient } from "@/lib/api-client";

export interface ActivityRange {
  /** ISO-8601 UTC instants; start inclusive, end exclusive. */
  start?: string;
  end?: string;
}

export interface FeedbackFilters extends ActivityRange {
  rating?: "up" | "down";
}

export interface FeedbackItem {
  id: string;
  message_id: string;
  conversation_id: string;
  user_id: string;
  rating: "up" | "down";
  comment: string | null;
  model_provider: string | null;
  model: string | null;
  created_at: string;
  updated_at: string;
}

export interface FeedbackSummary {
  up: number;
  down: number;
  total: number;
  /** null when there are no votes; this is satisfaction, not accuracy. */
  positive_percentage: number | null;
}

interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export const PAGE_SIZE = 25;

function clean(params: Record<string, string | number | undefined>) {
  return Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== ""),
  );
}

export class ActivityError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function getJson<T>(
  path: string,
  params: Record<string, string | number | undefined>,
): Promise<T> {
  const res = await apiClient.get<T>(path, { params: clean(params) });
  if (res.status < 200 || res.status >= 300) {
    throw new ActivityError(
      res.status === 403
        ? "You do not have access to Activity."
        : "Failed to load activity.",
      res.status,
    );
  }
  return res.data;
}

const feedbackParams = (f: FeedbackFilters) => ({
  start: f.start,
  end: f.end,
  rating: f.rating,
});
/** Keys include identity so one admin's cache is never shown to another. */
export function useFeedbackSummaryQuery(filters: FeedbackFilters) {
  const { user } = useAuth();
  return useQuery({
    queryKey: ["activity", user?.user_id, "feedback-summary", filters],
    queryFn: () =>
      getJson<FeedbackSummary>(
        "/activity/feedback/summary",
        feedbackParams(filters),
      ),
    retry: false,
  });
}

export function useFeedbackListQuery(filters: FeedbackFilters) {
  const { user } = useAuth();
  return useInfiniteQuery({
    // Filters are part of the key, so changing them discards old cursors.
    queryKey: ["activity", user?.user_id, "feedback", filters],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      getJson<Page<FeedbackItem>>("/activity/feedback", {
        ...feedbackParams(filters),
        limit: PAGE_SIZE,
        cursor: pageParam,
      }),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    retry: false,
  });
}
