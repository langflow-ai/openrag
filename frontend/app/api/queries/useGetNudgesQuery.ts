import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useCallback, useRef } from "react";
import { useChat } from "@/contexts/chat-context";
import { useProviderHealthQuery } from "./useProviderHealthQuery";

type Nudge = string;

const DEFAULT_NUDGES: Nudge[] = [];

// An empty result means "nothing to suggest yet" — usually a corpus still being
// ingested — so it is worth re-asking for a while. But it is also what an empty
// knowledge base returns forever, so the retries must be bounded: unbounded
// polling re-POSTs every 5s for as long as the chat page is open, and each
// request costs a real LLM completion when nudges run without Langflow.
const MAX_EMPTY_POLLS = 5;
const EMPTY_POLL_INTERVAL_MS = 5000;

export interface NudgeFilters {
  data_sources?: string[];
  document_types?: string[];
  owners?: string[];
}

export interface NudgeQueryParams {
  chatId?: string | null;
  filters?: NudgeFilters;
  limit?: number;
  scoreThreshold?: number;
}

export const useGetNudgesQuery = (
  params: NudgeQueryParams | null = {},
  options?: Omit<
    UseQueryOptions<Nudge[], Error, Nudge[]>,
    "queryKey" | "queryFn"
  >,
) => {
  const { chatId, filters, limit, scoreThreshold } = params ?? {};
  const queryClient = useQueryClient();
  const { isOnboardingComplete } = useChat();

  // Check if LLM provider is healthy
  // If health data is not available yet, assume healthy (optimistic)
  // Only disable if health data exists and shows LLM error
  const { data: health } = useProviderHealthQuery();
  const isLLMHealthy =
    health === undefined ||
    (health?.status === "healthy" && !health?.llm_error);

  // Tracked per query key so changing chat/filters starts the budget over.
  const pollKey = JSON.stringify([chatId, filters, limit, scoreThreshold]);
  const emptyAttemptsRef = useRef({ key: pollKey, count: 0 });
  if (emptyAttemptsRef.current.key !== pollKey) {
    emptyAttemptsRef.current = { key: pollKey, count: 0 };
  }

  function cancel() {
    emptyAttemptsRef.current.count = 0;
    queryClient.removeQueries({
      queryKey: ["nudges", chatId, filters, limit, scoreThreshold],
    });
  }

  async function getNudges(context: {
    signal?: AbortSignal;
  }): Promise<Nudge[]> {
    try {
      const requestBody: {
        filters?: NudgeFilters;
        limit?: number;
        score_threshold?: number;
      } = {};

      if (filters) {
        requestBody.filters = filters;
      }
      if (limit !== undefined) {
        requestBody.limit = limit;
      }
      if (scoreThreshold !== undefined) {
        requestBody.score_threshold = scoreThreshold;
      }

      const response = await fetch(`/api/nudges${chatId ? `/${chatId}` : ""}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
        signal: context.signal,
      });
      // A failed request is not "no nudges". Without this check an error body
      // parses fine, yields no `response` key, and is cached as an empty list,
      // which then keeps the retry loop below running indefinitely.
      if (!response.ok) {
        throw new Error(`Nudges request failed: ${response.status}`);
      }

      const data = await response.json();

      const nudges: Nudge[] =
        data.response && typeof data.response === "string"
          ? data.response.split("\n").filter(Boolean)
          : DEFAULT_NUDGES;

      emptyAttemptsRef.current.count =
        nudges.length === 0 ? emptyAttemptsRef.current.count + 1 : 0;

      return nudges;
    } catch (error) {
      // Ignore abort errors - these are expected when requests are cancelled
      if (error instanceof Error && error.name === "AbortError") {
        return DEFAULT_NUDGES;
      }
      console.error("Error getting nudges", error);
      // Rethrow so the query settles as an error rather than caching an empty
      // list. `data` then stays undefined and the retry loop stops.
      throw error;
    }
  }

  // Extract enabled from options and combine with onboarding completion and LLM health checks
  // Query is only enabled if onboarding is complete AND LLM provider is healthy AND the caller's enabled condition is met
  const callerEnabled = options?.enabled ?? true;
  const enabled = isOnboardingComplete && isLLMHealthy && callerEnabled;

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery(
    {
      queryKey: ["nudges", chatId, filters, limit, scoreThreshold],
      queryFn: getNudges,
      staleTime: 10000, // Consider data fresh for 10 seconds to prevent rapid refetching
      networkMode: "always", // Ensure requests can be cancelled
      refetchOnMount: false, // Don't refetch on every mount
      refetchOnWindowFocus: false, // Don't refetch when window regains focus
      refetchInterval: (query) => {
        // Retry while the result is empty, but only a bounded number of times.
        const data = query.state.data;
        if (!Array.isArray(data) || data.length > 0) {
          return false;
        }
        return emptyAttemptsRef.current.count < MAX_EMPTY_POLLS
          ? EMPTY_POLL_INTERVAL_MS
          : false;
      },
      ...options,
      enabled, // Override enabled after spreading options to ensure onboarding check is applied
    },
    queryClient,
  );

  // Callers refetch when the corpus changes (e.g. right after ingestion
  // completes), which is exactly when a previously-empty result should start
  // being worth retrying again. Re-arm the budget so the cap is not permanent.
  const refetchNudges: typeof refetch = useCallback(
    (...args) => {
      emptyAttemptsRef.current.count = 0;
      return refetch(...args);
    },
    [refetch],
  );

  return {
    data,
    isLoading,
    isError,
    error,
    refetch: refetchNudges,
    isFetching,
    cancel,
  };
};
