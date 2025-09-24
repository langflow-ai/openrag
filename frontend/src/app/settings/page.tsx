"use client";

import { Loader2, PlugZap, RefreshCw } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useUpdateFlowSettingMutation } from "@/app/api/mutations/useUpdateFlowSettingMutation";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { useGetOpenAIModelsQuery, useGetOllamaModelsQuery, useGetIBMModelsQuery } from "@/app/api/queries/useGetModelsQuery";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { ModelSelectItems } from "./helpers/model-select-item";
import { getFallbackModels, type ModelProvider } from "./helpers/model-helpers";
import { ProtectedRoute } from "@/components/protected-route";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/contexts/auth-context";
import { useTask } from "@/contexts/task-context";
import { useDebounce } from "@/lib/debounce";

const MAX_SYSTEM_PROMPT_CHARS = 2000;

interface GoogleDriveFile {
  id: string;
  name: string;
  mimeType: string;
  webViewLink?: string;
  iconLink?: string;
}

interface OneDriveFile {
  id: string;
  name: string;
  mimeType?: string;
  webUrl?: string;
  driveItem?: {
    file?: { mimeType: string };
    folder?: unknown;
  };
}

interface Connector {
  id: string;
  name: string;
  description: string;
  icon: React.ReactNode;
  status: "not_connected" | "connecting" | "connected" | "error";
  type: string;
  connectionId?: string;
  access_token?: string;
  selectedFiles?: GoogleDriveFile[] | OneDriveFile[];
}

interface SyncResult {
  processed?: number;
  added?: number;
  errors?: number;
  skipped?: number;
  total?: number;
}

interface Connection {
  connection_id: string;
  is_active: boolean;
  created_at: string;
  last_sync?: string;
}

function KnowledgeSourcesPage() {
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const { addTask, tasks } = useTask();
  const searchParams = useSearchParams();

  // Connectors state
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [isConnecting, setIsConnecting] = useState<string | null>(null);
  const [isSyncing, setIsSyncing] = useState<string | null>(null);
  const [syncResults, setSyncResults] = useState<{
    [key: string]: SyncResult | null;
  }>({});
  const [maxFiles, setMaxFiles] = useState<number>(10);
  const [syncAllFiles, setSyncAllFiles] = useState<boolean>(false);

  // Only keep systemPrompt state since it needs manual save button
  const [systemPrompt, setSystemPrompt] = useState<string>("");
  const [chunkSize, setChunkSize] = useState<number>(1024);
  const [chunkOverlap, setChunkOverlap] = useState<number>(50);
  const [processingMode, setProcessingMode] = useState<string>("standard");

  // Fetch settings using React Query
  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated,
  });

  // Get the current provider from settings
  const currentProvider = (settings.provider?.model_provider || 'openai') as ModelProvider;

  // Fetch available models based on provider
  const { data: openaiModelsData } = useGetOpenAIModelsQuery(
    undefined, // Let backend use stored API key from configuration
    {
      enabled: isAuthenticated && currentProvider === 'openai',
    }
  );

  const { data: ollamaModelsData } = useGetOllamaModelsQuery(
    undefined, // No params for now, could be extended later
    {
      enabled: isAuthenticated && currentProvider === 'ollama',
    }
  );

  const { data: ibmModelsData } = useGetIBMModelsQuery(
    undefined, // No params for now, could be extended later
    {
      enabled: isAuthenticated && currentProvider === 'ibm',
    }
  );

  // Select the appropriate models data based on provider
  const modelsData = currentProvider === 'openai'
    ? openaiModelsData
    : currentProvider === 'ollama'
    ? ollamaModelsData
    : currentProvider === 'ibm'
    ? ibmModelsData
    : openaiModelsData; // fallback to openai

  // Mutations
  const updateFlowSettingMutation = useUpdateFlowSettingMutation({
    onSuccess: () => {
      console.log("Setting updated successfully");
    },
    onError: (error) => {
      console.error("Failed to update setting:", error.message);
    },
  });


  // Debounced update function
  const debouncedUpdate = useDebounce(
    (variables: Parameters<typeof updateFlowSettingMutation.mutate>[0]) => {
      updateFlowSettingMutation.mutate(variables);
    },
    500,
  );

  // Sync system prompt state with settings data
  useEffect(() => {
    if (settings.agent?.system_prompt) {
      setSystemPrompt(settings.agent.system_prompt);
    }
  }, [settings.agent?.system_prompt]);

  // Sync chunk size and overlap state with settings data
  useEffect(() => {
    if (settings.knowledge?.chunk_size) {
      setChunkSize(settings.knowledge.chunk_size);
    }
  }, [settings.knowledge?.chunk_size]);

  useEffect(() => {
    if (settings.knowledge?.chunk_overlap) {
      setChunkOverlap(settings.knowledge.chunk_overlap);
    }
  }, [settings.knowledge?.chunk_overlap]);

  // Sync processing mode with settings data
  useEffect(() => {
    if (settings.knowledge?.doclingPresets) {
      setProcessingMode(settings.knowledge.doclingPresets);
    }
  }, [settings.knowledge?.doclingPresets]);

  // Update model selection immediately
  const handleModelChange = (newModel: string) => {
    updateFlowSettingMutation.mutate({ llm_model: newModel });
  };

  // Update system prompt with save button
  const handleSystemPromptSave = () => {
    updateFlowSettingMutation.mutate({ system_prompt: systemPrompt });
  };

  // Update embedding model selection immediately
  const handleEmbeddingModelChange = (newModel: string) => {
    updateFlowSettingMutation.mutate({ embedding_model: newModel });
  };

  // Update chunk size setting with debounce
  const handleChunkSizeChange = (value: string) => {
    const numValue = Math.max(0, parseInt(value) || 0);
    setChunkSize(numValue);
    debouncedUpdate({ chunk_size: numValue });
  };

  // Update chunk overlap setting with debounce
  const handleChunkOverlapChange = (value: string) => {
    const numValue = Math.max(0, parseInt(value) || 0);
    setChunkOverlap(numValue);
    debouncedUpdate({ chunk_overlap: numValue });
  };

  // Update processing mode
  const handleProcessingModeChange = (mode: string) => {
    setProcessingMode(mode);
    // Update the configuration setting (backend will also update the flow automatically)
    debouncedUpdate({ doclingPresets: mode });
  };


  // Helper function to get connector icon
  const getConnectorIcon = useCallback((iconName: string) => {
    const iconMap: { [key: string]: React.ReactElement } = {
      "google-drive": (
        <div className="w-8 h-8 bg-blue-600 rounded flex items-center justify-center text-white font-bold leading-none shrink-0">
          G
        </div>
      ),
      sharepoint: (
        <div className="w-8 h-8 bg-blue-700 rounded flex items-center justify-center text-white font-bold leading-none shrink-0">
          SP
        </div>
      ),
      onedrive: (
        <div className="w-8 h-8 bg-blue-400 rounded flex items-center justify-center text-white font-bold leading-none shrink-0">
          OD
        </div>
      ),
    };
    return (
      iconMap[iconName] || (
        <div className="w-8 h-8 bg-gray-500 rounded flex items-center justify-center text-white font-bold leading-none shrink-0">
          ?
        </div>
      )
    );
  }, []);

  // Connector functions
  const checkConnectorStatuses = useCallback(async () => {
    try {
      // Fetch available connectors from backend
      const connectorsResponse = await fetch("/api/connectors");
      if (!connectorsResponse.ok) {
        throw new Error("Failed to load connectors");
      }

      const connectorsResult = await connectorsResponse.json();
      const connectorTypes = Object.keys(connectorsResult.connectors);

      // Initialize connectors list with metadata from backend
      const initialConnectors = connectorTypes
        .filter((type) => connectorsResult.connectors[type].available) // Only show available connectors
        .map((type) => ({
          id: type,
          name: connectorsResult.connectors[type].name,
          description: connectorsResult.connectors[type].description,
          icon: getConnectorIcon(connectorsResult.connectors[type].icon),
          status: "not_connected" as const,
          type: type,
        }));

      setConnectors(initialConnectors);

      // Check status for each connector type

      for (const connectorType of connectorTypes) {
        const response = await fetch(`/api/connectors/${connectorType}/status`);
        if (response.ok) {
          const data = await response.json();
          const connections = data.connections || [];
          const activeConnection = connections.find(
            (conn: Connection) => conn.is_active,
          );
          const isConnected = activeConnection !== undefined;

          setConnectors((prev) =>
            prev.map((c) =>
              c.type === connectorType
                ? {
                    ...c,
                    status: isConnected ? "connected" : "not_connected",
                    connectionId: activeConnection?.connection_id,
                  }
                : c,
            ),
          );
        }
      }
    } catch (error) {
      console.error("Failed to check connector statuses:", error);
    }
  }, [getConnectorIcon]);

  const handleConnect = async (connector: Connector) => {
    setIsConnecting(connector.id);
    setSyncResults((prev) => ({ ...prev, [connector.id]: null }));

    try {
      // Use the shared auth callback URL, same as connectors page
      const redirectUri = `${window.location.origin}/auth/callback`;

      const response = await fetch("/api/auth/init", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          connector_type: connector.type,
          purpose: "data_source",
          name: `${connector.name} Connection`,
          redirect_uri: redirectUri,
        }),
      });

      if (response.ok) {
        const result = await response.json();

        if (result.oauth_config) {
          localStorage.setItem("connecting_connector_id", result.connection_id);
          localStorage.setItem("connecting_connector_type", connector.type);

          const authUrl =
            `${result.oauth_config.authorization_endpoint}?` +
            `client_id=${result.oauth_config.client_id}&` +
            `response_type=code&` +
            `scope=${result.oauth_config.scopes.join(" ")}&` +
            `redirect_uri=${encodeURIComponent(
              result.oauth_config.redirect_uri,
            )}&` +
            `access_type=offline&` +
            `prompt=consent&` +
            `state=${result.connection_id}`;

          window.location.href = authUrl;
        }
      } else {
        console.error("Failed to initiate connection");
        setIsConnecting(null);
      }
    } catch (error) {
      console.error("Connection error:", error);
      setIsConnecting(null);
    }
  };

  const handleSync = async (connector: Connector) => {
    if (!connector.connectionId) return;

    setIsSyncing(connector.id);
    setSyncResults((prev) => ({ ...prev, [connector.id]: null }));

    try {
      const syncBody: {
        connection_id: string;
        max_files?: number;
        selected_files?: string[];
      } = {
        connection_id: connector.connectionId,
        max_files: syncAllFiles ? 0 : maxFiles || undefined,
      };

      // Note: File selection is now handled via the cloud connectors dialog

      const response = await fetch(`/api/connectors/${connector.type}/sync`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(syncBody),
      });

      const result = await response.json();

      if (response.status === 201) {
        const taskId = result.task_id;
        if (taskId) {
          addTask(taskId);
          setSyncResults((prev) => ({
            ...prev,
            [connector.id]: {
              processed: 0,
              total: result.total_files || 0,
            },
          }));
        }
      } else if (response.ok) {
        setSyncResults((prev) => ({ ...prev, [connector.id]: result }));
        // Note: Stats will auto-refresh via task completion watcher for async syncs
      } else {
        console.error("Sync failed:", result.error);
      }
    } catch (error) {
      console.error("Sync error:", error);
    } finally {
      setIsSyncing(null);
    }
  };

  const getStatusBadge = (status: Connector["status"]) => {
    switch (status) {
      case "connected":
        return (
          <Badge
            variant="default"
            className="bg-green-500/20 text-green-400 border-green-500/30"
          >
            Connected
          </Badge>
        );
      case "connecting":
        return (
          <Badge
            variant="secondary"
            className="bg-yellow-500/20 text-yellow-400 border-yellow-500/30"
          >
            Connecting...
          </Badge>
        );
      case "error":
        return <Badge variant="destructive">Error</Badge>;
      default:
        return (
          <Badge
            variant="outline"
            className="bg-muted/20 text-muted-foreground border-muted whitespace-nowrap"
          >
            Not Connected
          </Badge>
        );
    }
  };

  // Check connector status on mount and when returning from OAuth
  useEffect(() => {
    if (isAuthenticated) {
      checkConnectorStatuses();
    }

    if (searchParams.get("oauth_success") === "true") {
      const url = new URL(window.location.href);
      url.searchParams.delete("oauth_success");
      window.history.replaceState({}, "", url.toString());
    }
  }, [searchParams, isAuthenticated, checkConnectorStatuses]);

  // Track previous tasks to detect new completions
  const [prevTasks, setPrevTasks] = useState<typeof tasks>([]);

  // Watch for task completions and refresh stats
  useEffect(() => {
    // Find newly completed tasks by comparing with previous state
    const newlyCompletedTasks = tasks.filter((task) => {
      const wasCompleted =
        prevTasks.find((prev) => prev.task_id === task.task_id)?.status ===
        "completed";
      return task.status === "completed" && !wasCompleted;
    });

    if (newlyCompletedTasks.length > 0) {
      // Task completed - could refresh data here if needed
      const timeoutId = setTimeout(() => {
        // Stats refresh removed
      }, 1000);

      // Update previous tasks state
      setPrevTasks(tasks);

      return () => clearTimeout(timeoutId);
    } else {
      // Always update previous tasks state
      setPrevTasks(tasks);
    }
  }, [tasks, prevTasks]);

  const handleEditInLangflow = (
    flowType: "chat" | "ingest",
    closeDialog: () => void,
  ) => {
    // Select the appropriate flow ID and edit URL based on flow type
    const targetFlowId =
      flowType === "ingest" ? settings.ingest_flow_id : settings.flow_id;
    const editUrl =
      flowType === "ingest"
        ? settings.langflow_ingest_edit_url
        : settings.langflow_edit_url;

    const derivedFromWindow =
      typeof window !== "undefined"
        ? `${window.location.protocol}//${window.location.hostname}:7860`
        : "";
    const base = (
      settings.langflow_public_url ||
      derivedFromWindow ||
      "http://localhost:7860"
    ).replace(/\/$/, "");
    const computed = targetFlowId ? `${base}/flow/${targetFlowId}` : base;

    const url = editUrl || computed;

    window.open(url, "_blank");
    closeDialog(); // Close immediately after opening Langflow
  };

  const handleRestoreRetrievalFlow = (closeDialog: () => void) => {
    fetch(`/api/reset-flow/retrieval`, {
      method: "POST",
    })
      .then((response) => response.json())
      .then(() => {
        closeDialog(); // Close after successful completion
      })
      .catch((error) => {
        console.error("Error restoring retrieval flow:", error);
        closeDialog(); // Close even on error (could show error toast instead)
      });
  };

  const handleRestoreIngestFlow = (closeDialog: () => void) => {
    fetch(`/api/reset-flow/ingest`, {
      method: "POST",
    })
      .then((response) => response.json())
      .then(() => {
        closeDialog(); // Close after successful completion
      })
      .catch((error) => {
        console.error("Error restoring ingest flow:", error);
        closeDialog(); // Close even on error (could show error toast instead)
      });
  };

  return (
    <div className="space-y-8">
      {/* Agent Behavior Section */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-lg">Agent</CardTitle>
              <CardDescription>
                Quick Agent settings. Edit in Langflow for full control.
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <ConfirmationDialog
                trigger={<Button variant="outline">Restore flow</Button>}
                title="Restore default Agent flow"
                description="This restores defaults and discards all custom settings and overrides. This can't be undone."
                confirmText="Restore"
                variant="destructive"
                onConfirm={handleRestoreRetrievalFlow}
              />
              <ConfirmationDialog
                trigger={
                  <Button>
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      width="24"
                      height="22"
                      viewBox="0 0 24 22"
                      className="h-4 w-4 mr-2"
                      aria-label="Langflow icon"
                    >
                      <title>Langflow icon</title>
                      <path
                        fill="currentColor"
                        d="M13.0486 0.462158H9.75399C9.44371 0.462158 9.14614 0.586082 8.92674 0.806667L4.03751 5.72232C3.81811 5.9429 3.52054 6.06682 3.21026 6.06682H1.16992C0.511975 6.06682 -0.0165756 6.61212 0.000397655 7.2734L0.0515933 9.26798C0.0679586 9.90556 0.586745 10.4139 1.22111 10.4139H3.59097C3.90124 10.4139 4.19881 10.2899 4.41821 10.0694L9.34823 5.11269C9.56763 4.89211 9.8652 4.76818 10.1755 4.76818H13.0486C13.6947 4.76818 14.2185 4.24157 14.2185 3.59195V1.63839C14.2185 0.988773 13.6947 0.462158 13.0486 0.462158Z"
                      ></path>
                      <path
                        fill="currentColor"
                        d="M19.5355 11.5862H22.8301C23.4762 11.5862 24 12.1128 24 12.7624V14.716C24 15.3656 23.4762 15.8922 22.8301 15.8922H19.957C19.6467 15.8922 19.3491 16.0161 19.1297 16.2367L14.1997 21.1934C13.9803 21.414 13.6827 21.5379 13.3725 21.5379H11.0026C10.3682 21.5379 9.84945 21.0296 9.83309 20.392L9.78189 18.3974C9.76492 17.7361 10.2935 17.1908 10.9514 17.1908H12.9918C13.302 17.1908 13.5996 17.0669 13.819 16.8463L18.7082 11.9307C18.9276 11.7101 19.2252 11.5862 19.5355 11.5862Z"
                      ></path>
                      <path
                        fill="currentColor"
                        d="M19.5355 2.9796L22.8301 2.9796C23.4762 2.9796 24 3.50622 24 4.15583V6.1094C24 6.75901 23.4762 7.28563 22.8301 7.28563H19.957C19.6467 7.28563 19.3491 7.40955 19.1297 7.63014L14.1997 12.5868C13.9803 12.8074 13.6827 12.9313 13.3725 12.9313H10.493C10.1913 12.9313 9.90126 13.0485 9.68346 13.2583L4.14867 18.5917C3.93087 18.8016 3.64085 18.9187 3.33917 18.9187H1.32174C0.675616 18.9187 0.151832 18.3921 0.151832 17.7425V15.7343C0.151832 15.0846 0.675616 14.558 1.32174 14.558H3.32468C3.63496 14.558 3.93253 14.4341 4.15193 14.2135L9.40827 8.92878C9.62767 8.70819 9.92524 8.58427 10.2355 8.58427H12.9918C13.302 8.58427 13.5996 8.46034 13.819 8.23976L18.7082 3.32411C18.9276 3.10353 19.2252 2.9796 19.5355 2.9796Z"
                      ></path>
                    </svg>
                    Edit in Langflow
                  </Button>
                }
                title="Edit Agent flow in Langflow"
                description="You're entering Langflow. You can edit the Agent flow and other underlying flows. Manual changes to components, wiring, or I/O can break this experience."
                confirmText="Proceed"
                onConfirm={(closeDialog) =>
                  handleEditInLangflow("chat", closeDialog)
                }
              />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="model-select" className="text-base font-medium">
                Language Model
              </Label>
              <Select
                value={settings.agent?.llm_model || modelsData?.language_models?.find(m => m.default)?.value || "gpt-4"}
                onValueChange={handleModelChange}
              >
                <SelectTrigger id="model-select">
                  <SelectValue placeholder="Select a model" />
                </SelectTrigger>
                <SelectContent>
                  <ModelSelectItems
                    models={modelsData?.language_models}
                    fallbackModels={getFallbackModels(currentProvider).language}
                    provider={currentProvider}
                  />
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="system-prompt" className="text-base font-medium">
                Agent Instructions
              </Label>
              <Textarea
                id="system-prompt"
                placeholder="Enter your agent instructions here..."
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                rows={6}
                className={`resize-none ${systemPrompt.length > MAX_SYSTEM_PROMPT_CHARS ? 'border-red-500 focus:border-red-500' : ''}`}
              />
              <div className="flex justify-start">
                <span className={`text-xs ${systemPrompt.length > MAX_SYSTEM_PROMPT_CHARS ? 'text-red-500' : 'text-muted-foreground'}`}>
                  {systemPrompt.length}/{MAX_SYSTEM_PROMPT_CHARS} characters
                </span>
              </div>
            </div>
            <div className="flex justify-end pt-2">
              <Button
                onClick={handleSystemPromptSave}
                disabled={updateFlowSettingMutation.isPending || systemPrompt.length > MAX_SYSTEM_PROMPT_CHARS}
                className="min-w-[120px]"
                size="sm"
                variant="outline"
              >
                {updateFlowSettingMutation.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Saving...
                  </>
                ) : (
                  "Save Agent Instructions"
                )}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Knowledge Ingest Section */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-lg">Knowledge</CardTitle>
              <CardDescription>
                Quick ingest options. Edit in Langflow for full control.
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <ConfirmationDialog
                trigger={<Button variant="outline">Restore flow</Button>}
                title="Restore default Ingest flow"
                description="This restores defaults and discards all custom settings and overrides. This can't be undone."
                confirmText="Restore"
                variant="destructive"
                onConfirm={handleRestoreIngestFlow}
              />
              <ConfirmationDialog
                trigger={
                  <Button>
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      width="24"
                      height="22"
                      viewBox="0 0 24 22"
                      className="h-4 w-4 mr-2"
                      aria-label="Langflow icon"
                    >
                      <title>Langflow icon</title>
                      <path
                        fill="currentColor"
                        d="M13.0486 0.462158H9.75399C9.44371 0.462158 9.14614 0.586082 8.92674 0.806667L4.03751 5.72232C3.81811 5.9429 3.52054 6.06682 3.21026 6.06682H1.16992C0.511975 6.06682 -0.0165756 6.61212 0.000397655 7.2734L0.0515933 9.26798C0.0679586 9.90556 0.586745 10.4139 1.22111 10.4139H3.59097C3.90124 10.4139 4.19881 10.2899 4.41821 10.0694L9.34823 5.11269C9.56763 4.89211 9.8652 4.76818 10.1755 4.76818H13.0486C13.6947 4.76818 14.2185 4.24157 14.2185 3.59195V1.63839C14.2185 0.988773 13.6947 0.462158 13.0486 0.462158Z"
                      ></path>
                      <path
                        fill="currentColor"
                        d="M19.5355 11.5862H22.8301C23.4762 11.5862 24 12.1128 24 12.7624V14.716C24 15.3656 23.4762 15.8922 22.8301 15.8922H19.957C19.6467 15.8922 19.3491 16.0161 19.1297 16.2367L14.1997 21.1934C13.9803 21.414 13.6827 21.5379 13.3725 21.5379H11.0026C10.3682 21.5379 9.84945 21.0296 9.83309 20.392L9.78189 18.3974C9.76492 17.7361 10.2935 17.1908 10.9514 17.1908H12.9918C13.302 17.1908 13.5996 17.0669 13.819 16.8463L18.7082 11.9307C18.9276 11.7101 19.2252 11.5862 19.5355 11.5862Z"
                      ></path>
                      <path
                        fill="currentColor"
                        d="M19.5355 2.9796L22.8301 2.9796C23.4762 2.9796 24 3.50622 24 4.15583V6.1094C24 6.75901 23.4762 7.28563 22.8301 7.28563H19.957C19.6467 7.28563 19.3491 7.40955 19.1297 7.63014L14.1997 12.5868C13.9803 12.8074 13.6827 12.9313 13.3725 12.9313H10.493C10.1913 12.9313 9.90126 13.0485 9.68346 13.2583L4.14867 18.5917C3.93087 18.8016 3.64085 18.9187 3.33917 18.9187H1.32174C0.675616 18.9187 0.151832 18.3921 0.151832 17.7425V15.7343C0.151832 15.0846 0.675616 14.558 1.32174 14.558H3.32468C3.63496 14.558 3.93253 14.4341 4.15193 14.2135L9.40827 8.92878C9.62767 8.70819 9.92524 8.58427 10.2355 8.58427H12.9918C13.302 8.58427 13.5996 8.46034 13.819 8.23976L18.7082 3.32411C18.9276 3.10353 19.2252 2.9796 19.5355 2.9796Z"
                      ></path>
                    </svg>
                    Edit in Langflow
                  </Button>
                }
                title="Edit Ingest flow in Langflow"
                description="You're entering Langflow. You can edit the Ingest flow and other underlying flows. Manual changes to components, wiring, or I/O can break this experience."
                confirmText="Proceed"
                onConfirm={(closeDialog) =>
                  handleEditInLangflow("ingest", closeDialog)
                }
              />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-6">
            <div className="space-y-2">
              <Label
                htmlFor="embedding-model-select"
                className="text-base font-medium"
              >
                Embedding Model
              </Label>
              <Select
                value={
                  settings.knowledge?.embedding_model || modelsData?.embedding_models?.find(m => m.default)?.value || "text-embedding-ada-002"
                }
                onValueChange={handleEmbeddingModelChange}
                disabled={true}
              >
                <SelectTrigger id="embedding-model-select" disabled={true}>
                  <SelectValue placeholder="Select an embedding model" />
                </SelectTrigger>
                <SelectContent>
                  <ModelSelectItems
                    models={modelsData?.embedding_models}
                    fallbackModels={getFallbackModels(currentProvider).embedding}
                    provider={currentProvider}
                  />
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="chunk-size" className="text-base font-medium">
                  Chunk Size
                </Label>
                <div className="relative">
                  <Input
                    id="chunk-size"
                    type="number"
                    min="1"
                    value={chunkSize}
                    onChange={(e) => handleChunkSizeChange(e.target.value)}
                    className="w-full pr-20"
                  />
                  <div className="absolute inset-y-0 right-0 flex items-center pr-8 pointer-events-none">
                    <span className="text-sm text-muted-foreground">
                      characters
                    </span>
                  </div>
                </div>
              </div>
              <div className="space-y-2">
                <Label
                  htmlFor="chunk-overlap"
                  className="text-base font-medium"
                >
                  Chunk Overlap
                </Label>
                <div className="relative">
                  <Input
                    id="chunk-overlap"
                    type="number"
                    min="0"
                    value={chunkOverlap}
                    onChange={(e) => handleChunkOverlapChange(e.target.value)}
                    className="w-full pr-20"
                  />
                  <div className="absolute inset-y-0 right-0 flex items-center pr-8 pointer-events-none">
                    <span className="text-sm text-muted-foreground">
                      characters
                    </span>
                  </div>
                </div>
              </div>
            </div>
            <div className="space-y-3">
              <Label className="text-base font-medium">Ingest Presets</Label>
              <RadioGroup
                value={processingMode}
                onValueChange={handleProcessingModeChange}
                className="space-y-3"
              >
                <div className="flex items-center space-x-3">
                  <RadioGroupItem value="standard" id="standard" />
                  <div className="flex-1">
                    <Label htmlFor="standard" className="text-base font-medium cursor-pointer">
                      Standard
                    </Label>
                    <div className="text-sm text-muted-foreground">
                      Fast ingest for text-based documents without images
                    </div>
                  </div>
                </div>
                <div className="flex items-center space-x-3">
                  <RadioGroupItem value="ocr" id="ocr" />
                  <div className="flex-1">
                    <Label htmlFor="ocr" className="text-base font-medium cursor-pointer">
                      Extract text from images
                    </Label>
                    <div className="text-sm text-muted-foreground">
                      Uses OCR to extract text from images/PDFs. Ingest is slower when enabled
                    </div>
                  </div>
                </div>
                <div className="flex items-center space-x-3">
                  <RadioGroupItem value="picture_description" id="picture_description" />
                  <div className="flex-1">
                    <Label htmlFor="picture_description" className="text-base font-medium cursor-pointer">
                      Generate Description
                    </Label>
                    <div className="text-sm text-muted-foreground">
                      Text extraction plust AI generated image descriptions
                    </div>
                  </div>
                </div>
                <div className="flex items-center space-x-3">
                  <RadioGroupItem value="VLM" id="VLM" />
                  <div className="flex-1">
                    <Label htmlFor="VLM" className="text-base font-medium cursor-pointer">
                      AI Vision
                    </Label>
                    <div className="text-sm text-muted-foreground">
                      Advanced processing with vision language models. Highest quality but most expensive
                    </div>
                  </div>
                </div>
              </RadioGroup>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Connectors Section */}
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight mb-2">
            Cloud Connectors
          </h2>
        </div>

        {/* Conditional Sync Settings or No-Auth Message */}
        {isNoAuthMode ? (
          <Card className="border-yellow-500/50 bg-yellow-500/5">
            <CardHeader>
              <CardTitle className="text-lg text-yellow-600">
                Cloud connectors are only available with auth mode enabled
              </CardTitle>
              <CardDescription className="text-sm">
                Please provide the following environment variables and restart:
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="bg-muted rounded-md p-4 font-mono text-sm">
                <div className="text-muted-foreground mb-2">
                  # make here https://console.cloud.google.com/apis/credentials
                </div>
                <div>GOOGLE_OAUTH_CLIENT_ID=</div>
                <div>GOOGLE_OAUTH_CLIENT_SECRET=</div>
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="flex items-center justify-between py-4">
            <div>
              <h3 className="text-lg font-medium">Sync Settings</h3>
              <p className="text-sm text-muted-foreground">
                Configure how many files to sync when manually triggering a sync
              </p>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="syncAllFiles"
                  checked={syncAllFiles}
                  onCheckedChange={(checked) => {
                    setSyncAllFiles(!!checked);
                    if (checked) {
                      setMaxFiles(0);
                    } else {
                      setMaxFiles(10);
                    }
                  }}
                />
                <Label
                  htmlFor="syncAllFiles"
                  className="font-medium whitespace-nowrap"
                >
                  Sync all files
                </Label>
              </div>
              <Label
                htmlFor="maxFiles"
                className="font-medium whitespace-nowrap"
              >
                Max files per sync:
              </Label>
              <div className="relative">
                <Input
                  id="maxFiles"
                  type="number"
                  value={syncAllFiles ? 0 : maxFiles}
                  onChange={(e) => setMaxFiles(parseInt(e.target.value) || 10)}
                  disabled={syncAllFiles}
                  className="w-16 min-w-16 max-w-16 flex-shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
                  min="1"
                  max="100"
                  title={
                    syncAllFiles
                      ? "Disabled when 'Sync all files' is checked"
                      : "Leave blank or set to 0 for unlimited"
                  }
                />
              </div>
            </div>
          </div>
        )}

        {/* Connectors Grid */}
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {connectors.map((connector) => (
            <Card key={connector.id} className="relative flex flex-col">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {connector.icon}
                    <div>
                      <CardTitle className="text-lg">
                        {connector.name}
                      </CardTitle>
                      <CardDescription className="text-sm">
                        {connector.description}
                      </CardDescription>
                    </div>
                  </div>
                  {getStatusBadge(connector.status)}
                </div>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col justify-end space-y-4">
                {connector.status === "connected" ? (
                  <div className="space-y-3">
                    <Button
                      onClick={() => handleSync(connector)}
                      disabled={isSyncing === connector.id}
                      className="w-full"
                      variant="outline"
                    >
                      {isSyncing === connector.id ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Syncing...
                        </>
                      ) : (
                        <>
                          <RefreshCw className="mr-2 h-4 w-4" />
                          Sync Now
                        </>
                      )}
                    </Button>

                    {syncResults[connector.id] && (
                      <div className="text-xs text-muted-foreground bg-muted/50 p-2 rounded">
                        <div>
                          Processed: {syncResults[connector.id]?.processed || 0}
                        </div>
                        <div>
                          Added: {syncResults[connector.id]?.added || 0}
                        </div>
                        {syncResults[connector.id]?.errors && (
                          <div>Errors: {syncResults[connector.id]?.errors}</div>
                        )}
                      </div>
                    )}
                  </div>
                ) : (
                  <Button
                    onClick={() => handleConnect(connector)}
                    disabled={isConnecting === connector.id}
                    className="w-full"
                  >
                    {isConnecting === connector.id ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Connecting...
                      </>
                    ) : (
                      <>
                        <PlugZap className="mr-2 h-4 w-4" />
                        Connect
                      </>
                    )}
                  </Button>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function ProtectedKnowledgeSourcesPage() {
  return (
    <ProtectedRoute>
      <Suspense fallback={<div>Loading knowledge sources...</div>}>
        <KnowledgeSourcesPage />
      </Suspense>
    </ProtectedRoute>
  );
}
