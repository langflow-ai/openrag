import {
  useQuery,
  useQueryClient,
  UseQueryOptions,
} from "@tanstack/react-query";

type Nudge = string;

const DEFAULT_NUDGES: Nudge[] = [];

export const useGetNudgesQuery = (
  chatId?: string | null,
  options?: Omit<UseQueryOptions, "queryKey" | "queryFn">
) => {
  const queryClient = useQueryClient();

  function cancel() {
    queryClient.removeQueries({ queryKey: ["nudges", chatId] });
  }

  async function getNudges(): Promise<Nudge[]> {
    try {
      const response = await fetch(`/api/nudges${chatId ? `/${chatId}` : ""}`);
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
      queryKey: ["nudges", chatId],
      queryFn: getNudges,
      ...options,
    },
    queryClient
  );

  return { ...queryResult, cancel };
};
