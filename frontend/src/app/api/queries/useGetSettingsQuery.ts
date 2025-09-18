import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

interface AgentSettings {
  llm_model?: string;
  system_prompt?: string;
}

interface IngestSettings {
  embedding_model?: string;
  chunk_size?: number;
  chunk_overlap?: number;
}

interface Settings {
  flow_id?: string;
  ingest_flow_id?: string;
  langflow_edit_url?: string;
  langflow_ingest_edit_url?: string;
  langflow_public_url?: string;
  agent?: AgentSettings;
  ingest?: IngestSettings;
}

export const useGetSettingsQuery = (
  options?: Omit<UseQueryOptions<Settings>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  async function getSettings(): Promise<Settings> {
    const response = await fetch("/api/settings");
    if (response.ok) {
      // Merge with defaults to ensure all properties exist
      return await response.json();
    } else {
      throw new Error("Failed to fetch settings");
    }
  }

  const queryResult = useQuery(
    {
      queryKey: ["settings"],
      queryFn: getSettings,
      ...options,
    },
    queryClient,
  );

  return queryResult;
};
