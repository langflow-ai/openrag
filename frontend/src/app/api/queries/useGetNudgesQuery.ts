import {
  useQuery,
  useQueryClient,
  UseQueryOptions,
} from "@tanstack/react-query";

type Nudge = string;

const DEFAULT_NUDGES = [
  "Show me this quarter's top 10 deals",
  "Summarize recent client interactions",
  "Search OpenSearch for mentions of our competitors",
];

export const useGetNudgesQuery = (
  chatId?: string | null,
  options?: Omit<UseQueryOptions, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  function cancel() {
    queryClient.removeQueries({ queryKey: ["nudges", chatId] });
  }

  async function getNudges(): Promise<Nudge[]> {
    try {
      const response = await fetch(`/api/nudges${chatId ? `/${chatId}` : ""}`);
      const data = await response.json();
      return data.response.split("\n").filter(Boolean) || DEFAULT_NUDGES;
    } catch (error) {
      console.error("Error getting nudges", error);
      return DEFAULT_NUDGES;
    }
  }

  const queryResult = useQuery(
    {
      queryKey: ["nudges", chatId],
      queryFn: getNudges,
      ...options,
    },
    queryClient,
  );

  return { ...queryResult, cancel };
};
