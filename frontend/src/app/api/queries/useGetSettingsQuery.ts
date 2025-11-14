import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export interface AgentSettings {
  llm_model?: string;
  llm_provider?: string;
  system_prompt?: string;
}

export interface KnowledgeSettings {
  embedding_model?: string;
  embedding_provider?: string;
  chunk_size?: number;
  chunk_overlap?: number;
  table_structure?: boolean;
  ocr?: boolean;
  picture_descriptions?: boolean;
}

export interface ProviderSettings {
  openai?: {
    has_api_key?: boolean;
    configured?: boolean;
  };
  anthropic?: {
    has_api_key?: boolean;
    configured?: boolean;
  };
  watsonx?: {
    has_api_key?: boolean;
    endpoint?: string;
    project_id?: string;
    configured?: boolean;
  };
  ollama?: {
    endpoint?: string;
    configured?: boolean;
  };
}

export interface Settings {
  langflow_url?: string;
  flow_id?: string;
  ingest_flow_id?: string;
  langflow_public_url?: string;
  edited?: boolean;
  providers?: ProviderSettings;
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
