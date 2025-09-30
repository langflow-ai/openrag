import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export interface AgentSettings {
  llm_model?: string;
  system_prompt?: string;
}

export interface KnowledgeSettings {
  embedding_model?: string;
  chunk_size?: number;
  chunk_overlap?: number;
  doclingPresets?: string;
}

export interface Settings {
  langflow_url?: string;
  flow_id?: string;
  ingest_flow_id?: string;
  langflow_public_url?: string;
  edited?: boolean;
  provider?: {
    model_provider?: string;
  };
  knowledge?: KnowledgeSettings;
  agent?: AgentSettings;
  langflow_edit_url?: string;
  langflow_ingest_edit_url?: string;
  ingestion_defaults?: {
    chunkSize?: number;
    chunkOverlap?: number;
    separator?: string;
    embeddingModel?: string;
  };
  localhost_url?: string;
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



