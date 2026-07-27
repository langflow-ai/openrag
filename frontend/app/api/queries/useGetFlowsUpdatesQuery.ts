import { useQuery } from "@tanstack/react-query";

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
      const response = await fetch("/api/settings/flows/updates-available");
      if (!response.ok) {
        throw new Error("Failed to fetch flow updates");
      }
      const data = await response.json();
      return data.updates as FlowUpdate[];
    },
    ...options,
  });
}
