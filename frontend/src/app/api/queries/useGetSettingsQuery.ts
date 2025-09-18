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

const DEFAULT_SETTINGS: Settings = {
  flow_id: "1098eea1-6649-4e1d-aed1-b77249fb8dd0",
  ingest_flow_id: "5488df7c-b93f-4f87-a446-b67028bc0813",
  langflow_edit_url: "",
  langflow_ingest_edit_url: "",
  langflow_public_url: "",
  agent: {
    llm_model: "gpt-4",
    system_prompt: "",
  },
  ingest: {
    embedding_model: "text-embedding-ada-002",
    chunk_size: 1000,
    chunk_overlap: 200,
  },
};

export const useGetSettingsQuery = (
  options?: Omit<UseQueryOptions<Settings>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  function cancel() {
    queryClient.removeQueries({ queryKey: ["settings"] });
  }

  async function getSettings(): Promise<Settings> {
    try {
      const response = await fetch("/api/settings");
      if (response.ok) {
        const settings = await response.json();
        // Merge with defaults to ensure all properties exist
        return {
          ...DEFAULT_SETTINGS,
          ...settings,
          agent: {
            ...DEFAULT_SETTINGS.agent,
            ...settings.agent,
          },
          ingest: {
            ...DEFAULT_SETTINGS.ingest,
            ...settings.ingest,
          },
        };
      } else {
        console.error("Failed to fetch settings");
        return DEFAULT_SETTINGS;
      }
    } catch (error) {
      console.error("Error getting settings", error);
      return DEFAULT_SETTINGS;
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

  return { ...queryResult, cancel };
};
