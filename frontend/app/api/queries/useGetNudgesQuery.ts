import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useChat } from "@/contexts/chat-context";
import { useProviderHealthQuery } from "./useProviderHealthQuery";

type Nudge = string;

const DEFAULT_NUDGES: Nudge[] = [];

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
  options?: Omit<UseQueryOptions, "queryKey" | "queryFn">,
) => {
  const { chatId, filters, limit, scoreThreshold } = params ?? {};
  const queryClient = useQueryClient();
  const { isOnboardingComplete } = useChat();
  
  // Check if LLM provider is healthy
  // If health data is not available yet, assume healthy (optimistic)
  // Only disable if health data exists and shows LLM error
  const { data: health } = useProviderHealthQuery();
  const isLLMHealthy = health === undefined || (health?.status === "healthy" && !health?.llm_error);

  function cancel() {
    queryClient.removeQueries({
      queryKey: ["nudges", chatId, filters, limit, scoreThreshold],
    });
  }

  async function getNudges(context: { signal?: AbortSignal }): Promise<Nudge[]> {
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
      const data = await response.json();

      if (data.response && typeof data.response === "string") {
        return data.response.split("\n").filter(Boolean);
      }

      return DEFAULT_NUDGES;
    } catch (error) {
      // Ignore abort errors - these are expected when requests are cancelled
      if (error instanceof Error && error.name === 'AbortError') {
        return DEFAULT_NUDGES;
      }
      console.error("Error getting nudges", error);
      return DEFAULT_NUDGES;
    }
  }

  // Extract enabled from options and combine with onboarding completion and LLM health checks
  // Query is only enabled if onboarding is complete AND LLM provider is healthy AND the caller's enabled condition is met
  const callerEnabled = options?.enabled ?? true;
  const enabled = isOnboardingComplete && isLLMHealthy && callerEnabled;

  const queryResult = useQuery(
    {
      queryKey: ["nudges", chatId, filters, limit, scoreThreshold],
      queryFn: getNudges,
      staleTime: 10000, // Consider data fresh for 10 seconds to prevent rapid refetching
      networkMode: 'always', // Ensure requests can be cancelled
      refetchOnMount: false, // Don't refetch on every mount
      refetchOnWindowFocus: false, // Don't refetch when window regains focus
      refetchInterval: (query) => {
        // If data is empty, refetch every 5 seconds
        const data = query.state.data;
        return Array.isArray(data) && data.length === 0 ? 5000 : false;
      },
      ...options,
      enabled, // Override enabled after spreading options to ensure onboarding check is applied
    },
    queryClient,
  );

  return { ...queryResult, cancel };
};
