import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useChat } from "@/contexts/chat-context";
import { usePermissions } from "@/hooks/use-permissions";
import { useGetSettingsQuery } from "./useGetSettingsQuery";
import { useGetTasksQuery } from "./useGetTasksQuery";

export interface ProviderHealthDetails {
  llm_model: string;
  embedding_model: string;
  endpoint?: string | null;
}

export interface ProviderHealthResponse {
  status: "healthy" | "unhealthy" | "error" | "backend-unavailable";
  message: string;
  provider?: string;
  llm_provider?: string;
  embedding_provider?: string;
  llm_error?: string | null;
  embedding_error?: string | null;
  details?: ProviderHealthDetails;
}

export interface ProviderHealthParams {
  provider?: "openai" | "ollama" | "watsonx";
  test_completion?: boolean;
}

// Track consecutive failures for exponential backoff
const failureCountMap = new Map<string, number>();

export const useProviderHealthQuery = (
  params?: ProviderHealthParams,
  options?: Omit<
    UseQueryOptions<ProviderHealthResponse, Error>,
    "queryKey" | "queryFn"
  >,
) => {
  const queryClient = useQueryClient();

  // Get chat error state and onboarding completion from context (ChatProvider wraps the entire app in layout.tsx)
  const { hasChatError, setChatError, isOnboardingComplete } = useChat();

  // Provider health is admin-only (backend gates /provider/health on
  // providers:read). Don't poll it for non-admins under enforced RBAC —
  // it would only 403. When RBAC is off, behave exactly as before.
  const { can, rbacEnforced } = usePermissions();
  const providerHealthAllowed = !rbacEnforced || can("providers:read");

  const { data: settings = {} } = useGetSettingsQuery();

  // Check if there are any active ingestion tasks
  const { data: tasks = [] } = useGetTasksQuery();
  const hasActiveIngestion = tasks.some(
    (task) =>
      task.status === "pending" ||
      task.status === "running" ||
      task.status === "processing",
  );

  async function checkProviderHealth(): Promise<ProviderHealthResponse> {
    try {
      const url = new URL("/api/provider/health", window.location.origin);

      if (params?.provider) {
        url.searchParams.set("provider", params.provider);
      }

      // After chat/ingest failure, run a completion check so the banner shows
      // the real cause (disabled key vs missing model). Otherwise lightweight.
      const testCompletion = params?.test_completion ?? hasChatError;
      if (testCompletion) {
        url.searchParams.set("test_completion", "true");
      }

      const response = await fetch(url.toString());

      if (response.ok) {
        const data = (await response.json()) as ProviderHealthResponse;
        if (hasChatError) {
          setChatError(false);
        }
        return data;
      } else if (response.status === 503) {
        const errorData = await response.json().catch(() => ({}));
        return {
          status: "unhealthy",
          message: errorData.message || "Provider validation failed",
          provider: errorData.provider || params?.provider || "unknown",
          llm_provider: errorData.llm_provider,
          embedding_provider: errorData.embedding_provider,
          llm_error: errorData.llm_error,
          embedding_error: errorData.embedding_error,
          details: errorData.details,
        };
      } else {
        const errorData = await response.json().catch(() => ({}));
        return {
          status: "error",
          message: errorData.message || "Failed to check provider health",
          provider: errorData.provider || params?.provider || "unknown",
          llm_provider: errorData.llm_provider,
          embedding_provider: errorData.embedding_provider,
          llm_error: errorData.llm_error,
          embedding_error: errorData.embedding_error,
          details: errorData.details,
        };
      }
    } catch (error) {
      return {
        status: "backend-unavailable",
        message: error instanceof Error ? error.message : "Connection failed",
        provider: params?.provider || "unknown",
      };
    }
  }

  // hasChatError in the key forces an immediate refetch when chat/ingest fails.
  const testCompletion = params?.test_completion ?? hasChatError;
  const queryKey = ["provider", "health", testCompletion, hasChatError];
  const failureCountKey = queryKey.join("-");

  const isEnabled =
    !!settings?.edited &&
    isOnboardingComplete &&
    !hasActiveIngestion &&
    providerHealthAllowed &&
    options?.enabled !== false;

  const query = useQuery(
    {
      queryKey,
      queryFn: checkProviderHealth,
      retry: false,
      refetchInterval: (query) => {
        const data = query.state.data;
        const status = data?.status;

        if (status === "healthy") {
          failureCountMap.set(failureCountKey, 0);
          return 30000;
        }

        if (status === "backend-unavailable") {
          return 15000;
        }

        // Keep probing while latched so fixing the real cause updates the banner
        // within seconds (key re-enable or model change).
        if (hasChatError) {
          return 5000;
        }

        const currentFailures = failureCountMap.get(failureCountKey) || 0;
        failureCountMap.set(failureCountKey, currentFailures + 1);
        const backoffDelays = [5000, 10000, 20000, 30000];
        return backoffDelays[
          Math.min(currentFailures, backoffDelays.length - 1)
        ];
      },
      refetchOnWindowFocus: false,
      refetchOnMount: true,
      staleTime: 30000,
      ...options,
      enabled: isEnabled,
    },
    queryClient,
  );

  return { ...query, isEnabled };
};
