import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

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

  function cancel() {
    queryClient.removeQueries({
      queryKey: ["nudges", chatId, filters, limit, scoreThreshold],
    });
  }

  async function getNudges(): Promise<Nudge[]> {
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
      });
      const data = await response.json();

      if (data.response && typeof data.response === "string") {
        return data.response.split("\n").filter(Boolean);
      }

      return DEFAULT_NUDGES;
    } catch (error) {
      console.error("Error getting nudges", error);
      return DEFAULT_NUDGES;
    }
  }

  const queryResult = useQuery(
    {
      queryKey: ["nudges", chatId, filters, limit, scoreThreshold],
      queryFn: getNudges,
      ...options,
    },
    queryClient,
  );

  return { ...queryResult, cancel };
};
