import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export type FlowUpdate = {
  flow_type: "nudges" | "retrieval" | "ingest" | "url_ingest";
  flow_id: string;
  is_custom: boolean;
  dismissed: boolean;
};

export function useGetFlowsUpdatesQuery(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ["flows", "updates-available"],
    queryFn: async () => {
      const response = await apiClient.get<{ updates: FlowUpdate[] }>(
        "/settings/flows/updates-available",
      );
      if (response.status < 200 || response.status >= 300) {
        throw new Error("Failed to fetch flow updates");
      }
      const data = response.data;
      return data.updates as FlowUpdate[];
    },
    ...options,
  });
}
