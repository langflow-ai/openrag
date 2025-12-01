"use client";

import { ArrowUpRight, Loader2, Minus, PlugZap, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
	useGetAnthropicModelsQuery,
	useGetIBMModelsQuery,
	useGetOllamaModelsQuery,
	useGetOpenAIModelsQuery,
} from "@/app/api/queries/useGetModelsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { LabelWrapper } from "@/components/label-wrapper";
import { ProtectedRoute } from "@/components/protected-route";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/contexts/auth-context";
import { useTask } from "@/contexts/task-context";
import {
	DEFAULT_AGENT_SETTINGS,
	DEFAULT_KNOWLEDGE_SETTINGS,
	UI_CONSTANTS,
} from "@/lib/constants";
import { useDebounce } from "@/lib/debounce";
import { cn } from "@/lib/utils";
import GoogleDriveIcon from "../../components/icons/google-drive-logo";
import OneDriveIcon from "../../components/icons/one-drive-logo";
import SharePointIcon from "../../components/icons/share-point-logo";
import { useUpdateSettingsMutation } from "../api/mutations/useUpdateSettingsMutation";
import { ModelSelector } from "../onboarding/_components/model-selector";
import ModelProviders from "./_components/model-providers";
import { getModelLogo, type ModelProvider } from "./_helpers/model-helpers";

const { MAX_SYSTEM_PROMPT_CHARS } = UI_CONSTANTS;

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
	available?: boolean;
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
	const router = useRouter();

	// Check if we should auto-open the LLM model selector
	const focusLlmModel = searchParams.get("focusLlmModel") === "true";
	// Use a trigger state that changes each time we detect the query param
	const [openLlmSelector, setOpenLlmSelector] = useState(false);

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
	const [tableStructure, setTableStructure] = useState<boolean>(true);
	const [ocr, setOcr] = useState<boolean>(false);
	const [pictureDescriptions, setPictureDescriptions] =
		useState<boolean>(false);

	// Fetch settings using React Query
	const { data: settings = {} } = useGetSettingsQuery({
		enabled: isAuthenticated || isNoAuthMode,
	});

	// Fetch models for each provider
	const { data: openaiModels, isLoading: openaiLoading } =
		useGetOpenAIModelsQuery(
			{ apiKey: "" },
			{ enabled: settings?.providers?.openai?.configured === true },
		);

	const { data: anthropicModels, isLoading: anthropicLoading } =
		useGetAnthropicModelsQuery(
			{ apiKey: "" },
			{ enabled: settings?.providers?.anthropic?.configured === true },
		);

	const { data: ollamaModels, isLoading: ollamaLoading } =
		useGetOllamaModelsQuery(
			{ endpoint: settings?.providers?.ollama?.endpoint },
			{
				enabled:
					settings?.providers?.ollama?.configured === true &&
					!!settings?.providers?.ollama?.endpoint,
			},
		);

	const { data: watsonxModels, isLoading: watsonxLoading } =
		useGetIBMModelsQuery(
			{
				endpoint: settings?.providers?.watsonx?.endpoint,
				apiKey: "",
				projectId: settings?.providers?.watsonx?.project_id,
			},
			{
				enabled:
					settings?.providers?.watsonx?.configured === true &&
					!!settings?.providers?.watsonx?.endpoint &&
					!!settings?.providers?.watsonx?.project_id,
			},
		);

	// Build grouped LLM model options from all configured providers
	const groupedLlmModels = [
		{
			group: "OpenAI",
			provider: "openai",
			icon: getModelLogo("", "openai"),
			models: openaiModels?.language_models || [],
			configured: settings.providers?.openai?.configured === true,
		},
		{
			group: "Anthropic",
			provider: "anthropic",
			icon: getModelLogo("", "anthropic"),
			models: anthropicModels?.language_models || [],
			configured: settings.providers?.anthropic?.configured === true,
		},
		{
			group: "Ollama",
			provider: "ollama",
			icon: getModelLogo("", "ollama"),
			models: ollamaModels?.language_models || [],
			configured: settings.providers?.ollama?.configured === true,
		},
		{
			group: "IBM watsonx.ai",
			provider: "watsonx",
			icon: getModelLogo("", "watsonx"),
			models: watsonxModels?.language_models || [],
			configured: settings.providers?.watsonx?.configured === true,
		},
	]
		.filter((provider) => provider.configured)
		.map((provider) => ({
			group: provider.group,
			icon: provider.icon,
			options: provider.models.map((model) => ({
				...model,
				provider: provider.provider,
			})),
		}));

	// Build grouped embedding model options from all configured providers (excluding Anthropic)
	const groupedEmbeddingModels = [
		{
			group: "OpenAI",
			provider: "openai",
			icon: getModelLogo("", "openai"),
			models: openaiModels?.embedding_models || [],
			configured: settings.providers?.openai?.configured === true,
		},
		{
			group: "Ollama",
			provider: "ollama",
			icon: getModelLogo("", "ollama"),
			models: ollamaModels?.embedding_models || [],
			configured: settings.providers?.ollama?.configured === true,
		},
		{
			group: "IBM watsonx.ai",
			provider: "watsonx",
			icon: getModelLogo("", "watsonx"),
			models: watsonxModels?.embedding_models || [],
			configured: settings.providers?.watsonx?.configured === true,
		},
	]
		.filter((provider) => provider.configured)
		.map((provider) => ({
			group: provider.group,
			icon: provider.icon,
			options: provider.models.map((model) => ({
				...model,
				provider: provider.provider,
			})),
		}));

	const isLoadingAnyLlmModels =
		openaiLoading || anthropicLoading || ollamaLoading || watsonxLoading;
	const isLoadingAnyEmbeddingModels =
		openaiLoading || ollamaLoading || watsonxLoading;

	// Mutations
	const updateSettingsMutation = useUpdateSettingsMutation({
		onSuccess: () => {
			toast.success("Settings updated successfully");
		},
		onError: (error) => {
			toast.error("Failed to update settings", {
				description: error.message,
			});
		},
	});

	// Debounced update function
	const debouncedUpdate = useDebounce(
		(variables: Parameters<typeof updateSettingsMutation.mutate>[0]) => {
			updateSettingsMutation.mutate(variables);
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

	// Sync docling settings with settings data
	useEffect(() => {
		if (settings.knowledge?.table_structure !== undefined) {
			setTableStructure(settings.knowledge.table_structure);
		}
	}, [settings.knowledge?.table_structure]);

	useEffect(() => {
		if (settings.knowledge?.ocr !== undefined) {
			setOcr(settings.knowledge.ocr);
		}
	}, [settings.knowledge?.ocr]);

	useEffect(() => {
		if (settings.knowledge?.picture_descriptions !== undefined) {
			setPictureDescriptions(settings.knowledge.picture_descriptions);
		}
	}, [settings.knowledge?.picture_descriptions]);

	// Handle auto-focus on LLM model selector when coming from provider setup
	useEffect(() => {
		if (focusLlmModel) {
			// Trigger the selector to open
			setOpenLlmSelector(true);

			// Scroll to the agent card
			const agentCard = document.getElementById("agent-card");
			if (agentCard) {
				agentCard.scrollIntoView({ behavior: "smooth", block: "start" });
			}

			// Clear the query parameter
			const newSearchParams = new URLSearchParams(searchParams.toString());
			newSearchParams.delete("focusLlmModel");
			router.replace(`/settings?${newSearchParams.toString()}`, {
				scroll: false,
			});

			// Reset the trigger after a brief delay so it can be triggered again
			setTimeout(() => setOpenLlmSelector(false), 100);
		}
	}, [focusLlmModel, searchParams, router]);

	// Update model selection immediately (also updates provider)
	const handleModelChange = (newModel: string, provider?: string) => {
		if (newModel && provider) {
			updateSettingsMutation.mutate({
				llm_model: newModel,
				llm_provider: provider,
			});
		} else if (newModel) {
			updateSettingsMutation.mutate({ llm_model: newModel });
		}
	};

	// Update system prompt with save button
	const handleSystemPromptSave = () => {
		updateSettingsMutation.mutate({ system_prompt: systemPrompt });
	};

	// Update embedding model selection immediately (also updates provider)
	const handleEmbeddingModelChange = (newModel: string, provider?: string) => {
		if (newModel && provider) {
			updateSettingsMutation.mutate({
				embedding_model: newModel,
				embedding_provider: provider,
			});
		} else if (newModel) {
			updateSettingsMutation.mutate({ embedding_model: newModel });
		}
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

	// Update docling settings
	const handleTableStructureChange = (checked: boolean) => {
		setTableStructure(checked);
		updateSettingsMutation.mutate({ table_structure: checked });
	};

	const handleOcrChange = (checked: boolean) => {
		setOcr(checked);
		updateSettingsMutation.mutate({ ocr: checked });
	};

	const handlePictureDescriptionsChange = (checked: boolean) => {
		setPictureDescriptions(checked);
		updateSettingsMutation.mutate({ picture_descriptions: checked });
	};

	// Helper function to get connector icon
	const getConnectorIcon = useCallback((iconName: string) => {
		const iconMap: { [key: string]: React.ReactElement } = {
			"google-drive": <GoogleDriveIcon />,
			sharepoint: <SharePointIcon />,
			onedrive: <OneDriveIcon />,
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
				// .filter((type) => connectorsResult.connectors[type].available) // Only show available connectors
				.map((type) => ({
					id: type,
					name: connectorsResult.connectors[type].name,
					description: connectorsResult.connectors[type].description,
					icon: getConnectorIcon(connectorsResult.connectors[type].icon),
					status: "not_connected" as const,
					type: type,
					available: connectorsResult.connectors[type].available,
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

	// const handleSync = async (connector: Connector) => {
	//   if (!connector.connectionId) return;

	//   setIsSyncing(connector.id);
	//   setSyncResults(prev => ({ ...prev, [connector.id]: null }));

	//   try {
	//     const syncBody: {
	//       connection_id: string;
	//       max_files?: number;
	//       selected_files?: string[];
	//     } = {
	//       connection_id: connector.connectionId,
	//       max_files: syncAllFiles ? 0 : maxFiles || undefined,
	//     };

	//     // Note: File selection is now handled via the cloud connectors dialog

	//     const response = await fetch(`/api/connectors/${connector.type}/sync`, {
	//       method: "POST",
	//       headers: {
	//         "Content-Type": "application/json",
	//       },
	//       body: JSON.stringify(syncBody),
	//     });

	//     const result = await response.json();

	//     if (response.status === 201) {
	//       const taskId = result.task_id;
	//       if (taskId) {
	//         addTask(taskId);
	//         setSyncResults(prev => ({
	//           ...prev,
	//           [connector.id]: {
	//             processed: 0,
	//             total: result.total_files || 0,
	//           },
	//         }));
	//       }
	//     } else if (response.ok) {
	//       setSyncResults(prev => ({ ...prev, [connector.id]: result }));
	//       // Note: Stats will auto-refresh via task completion watcher for async syncs
	//     } else {
	//       console.error("Sync failed:", result.error);
	//     }
	//   } catch (error) {
	//     console.error("Sync error:", error);
	//   } finally {
	//     setIsSyncing(null);
	//   }
	// };

	const navigateToKnowledgePage = (connector: Connector) => {
		const provider = connector.type.replace(/-/g, "_");
		router.push(`/upload/${provider}`);
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
			.then((response) => {
				if (response.ok) {
					return response.json();
				}
				throw new Error(`HTTP ${response.status}: ${response.statusText}`);
			})
			.then(() => {
				// Flow restoration is complete - backend already updated flow with current provider/model
				// Just reset the UI form value for system prompt
				setSystemPrompt(DEFAULT_AGENT_SETTINGS.system_prompt);
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
			.then((response) => {
				if (response.ok) {
					return response.json();
				}
				throw new Error(`HTTP ${response.status}: ${response.statusText}`);
			})
			.then(() => {
				// Only reset form values if the API call was successful
				setChunkSize(DEFAULT_KNOWLEDGE_SETTINGS.chunk_size);
				setChunkOverlap(DEFAULT_KNOWLEDGE_SETTINGS.chunk_overlap);
				setTableStructure(false);
				setOcr(false);
				setPictureDescriptions(false);
				closeDialog(); // Close after successful completion
			})
			.catch((error) => {
				console.error("Error restoring ingest flow:", error);
				closeDialog(); // Close even on error (could show error toast instead)
			});
	};

	return (
		<div className="space-y-8 pb-6">
			{/* Connectors Section */}
			<div className="space-y-6">
				<div>
					<h2 className="text-lg font-semibold tracking-tight mb-2">
						Cloud Connectors
					</h2>
				</div>

				{/* Conditional Sync Settings or No-Auth Message */}
				{
					isNoAuthMode ? (
						<Card className="border-accent-amber-foreground">
							<CardHeader>
								<CardTitle className="text-lg">
									Cloud connectors require authentication
								</CardTitle>
								<CardDescription className="text-sm">
									Add the Google OAuth variables below to your <code>.env</code>{" "}
									then restart the OpenRAG containers.
								</CardDescription>
							</CardHeader>
							<CardContent>
								<div className="bg-muted rounded-md p-4 font-mono text-sm">
									<div className="text-muted-foreground">
										<div>
											<span className="mr-3 text-placeholder-foreground">
												27
											</span>
											<span># Google OAuth</span>
										</div>
										<div>
											<span className="mr-3 text-placeholder-foreground">
												28
											</span>
											<span># Create credentials here:</span>
										</div>
										<div>
											<span className="mr-3 text-placeholder-foreground">
												29
											</span>
											<span>
												# https://console.cloud.google.com/apis/credentials
											</span>
										</div>
									</div>
									<div>
										<span className="mr-3 text-placeholder-foreground">30</span>
										<span>GOOGLE_OAUTH_CLIENT_ID=</span>
									</div>
									<div>
										<span className="mr-3 text-placeholder-foreground">31</span>
										<span>GOOGLE_OAUTH_CLIENT_SECRET=</span>
									</div>
								</div>
							</CardContent>
						</Card>
					) : null
					// <div className="flex items-center justify-between py-4">
					//   <div>
					//     <h3 className="text-lg font-medium">Sync Settings</h3>
					//     <p className="text-sm text-muted-foreground">
					//       Configure how many files to sync when manually triggering a sync
					//     </p>
					//   </div>
					//   <div className="flex items-center gap-4">
					//     <div className="flex items-center space-x-2">
					//       <Checkbox
					//         id="syncAllFiles"
					//         checked={syncAllFiles}
					//         onCheckedChange={checked => {
					//           setSyncAllFiles(!!checked);
					//           if (checked) {
					//             setMaxFiles(0);
					//           } else {
					//             setMaxFiles(10);
					//           }
					//         }}
					//       />
					//       <Label
					//         htmlFor="syncAllFiles"
					//         className="font-medium whitespace-nowrap"
					//       >
					//         Sync all files
					//       </Label>
					//     </div>
					//     <Label
					//       htmlFor="maxFiles"
					//       className="font-medium whitespace-nowrap"
					//     >
					//       Max files per sync:
					//     </Label>
					//     <div className="relative">
					//       <Input
					//         id="maxFiles"
					//         type="number"
					//         value={syncAllFiles ? 0 : maxFiles}
					//         onChange={e => setMaxFiles(parseInt(e.target.value) || 10)}
					//         disabled={syncAllFiles}
					//         className="w-16 min-w-16 max-w-16 flex-shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
					//         min="1"
					//         max="100"
					//         title={
					//           syncAllFiles
					//             ? "Disabled when 'Sync all files' is checked"
					//             : "Leave blank or set to 0 for unlimited"
					//         }
					//       />
					//     </div>
					//   </div>
					// </div>
				}
				{/* Connectors Grid */}
				<div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
					{connectors.map((connector) => {
						return (
							<Card key={connector.id} className="relative flex flex-col">
								<CardHeader className="pb-2">
									<div className="flex flex-col items-start justify-between">
										<div className="flex flex-col gap-3">
											<div className="mb-1">
												<div
													className={cn(
														"w-8 h-8 rounded flex items-center justify-center border",
														connector?.available
															? "bg-white"
															: "bg-muted grayscale",
													)}
												>
													{connector.icon}
												</div>
											</div>
											<CardTitle className="flex flex-row items-center gap-2">
												{connector.name}
											</CardTitle>
											<CardDescription className="text-sm">
												{connector?.available
													? `${connector.name} is configured.`
													: "Not configured."}
											</CardDescription>
										</div>
									</div>
								</CardHeader>
								<CardContent className="flex-1 flex flex-col justify-end space-y-4">
									{connector?.available ? (
										<div className="space-y-3">
											{connector?.status === "connected" ? (
												<>
													<Button
														variant="outline"
														onClick={() => navigateToKnowledgePage(connector)}
														disabled={isSyncing === connector.id}
														className="w-full cursor-pointer"
														size="sm"
													>
														<Plus className="h-4 w-4" />
														Add Knowledge
													</Button>
													{syncResults[connector.id] && (
														<div className="text-xs text-muted-foreground bg-muted/50 p-2 rounded">
															<div>
																Processed:{" "}
																{syncResults[connector.id]?.processed || 0}
															</div>
															<div>
																Added: {syncResults[connector.id]?.added || 0}
															</div>
															{syncResults[connector.id]?.errors && (
																<div>
																	Errors: {syncResults[connector.id]?.errors}
																</div>
															)}
														</div>
													)}
												</>
											) : (
												<Button
													onClick={() => handleConnect(connector)}
													disabled={isConnecting === connector.id}
													className="w-full cursor-pointer"
													size="sm"
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
										</div>
									) : (
										<div className="text-sm text-muted-foreground">
											<p>
												See our{" "}
												<Link
													className="text-accent-pink-foreground"
													href="https://docs.openr.ag/knowledge#oauth-ingestion"
													target="_blank"
													rel="noopener noreferrer"
												>
													Cloud Connectors installation guide
												</Link>{" "}
												for more detail.
											</p>
										</div>
									)}
								</CardContent>
							</Card>
						);
					})}
				</div>
			</div>

			{/* Model Providers Section */}
			<div className="space-y-6">
				<div>
					<h2 className="text-lg font-semibold tracking-tight mb-2">
						Model Providers
					</h2>
				</div>
				<ModelProviders />
			</div>

			{/* Agent Behavior Section */}
			<Card id="agent-card">
				<CardHeader>
					<div className="flex items-center justify-between mb-3">
						<CardTitle className="text-lg">Agent</CardTitle>
						<div className="flex gap-2">
							<ConfirmationDialog
								trigger={
									<Button ignoreTitleCase={true} variant="outline">
										Restore flow
									</Button>
								}
								title="Restore default Agent flow"
								description="This restores defaults and discards all custom settings and overrides. This can’t be undone."
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
								description={
									<>
										<p className="mb-2">
											You&apos;re entering Langflow. You can edit the{" "}
											<b>Agent flow</b> and other underlying flows. Manual
											changes to components, wiring, or I/O can break this
											experience.
										</p>
										<p className="mb-2">
											To enable editing, you need to unlock the flow by clicking
											on its name and disabling the <b>Lock flow</b> option.
										</p>
										<p>You can restore this flow from Settings.</p>
									</>
								}
								confirmText="Proceed"
								confirmIcon={<ArrowUpRight />}
								onConfirm={(closeDialog) =>
									handleEditInLangflow("chat", closeDialog)
								}
								variant="warning"
							/>
						</div>
					</div>
					<CardDescription>
						This Agent retrieves from your knowledge and generates chat
						responses. Edit in Langflow for full control.
					</CardDescription>
				</CardHeader>
				<CardContent>
					<div className="space-y-6">
						<div className="space-y-2">
							<LabelWrapper
								label="Language model"
								helperText="Model used for chat"
								id="language-model"
								required={true}
							>
								<ModelSelector
									groupedOptions={groupedLlmModels}
									noOptionsPlaceholder={
										isLoadingAnyLlmModels
											? "Loading models..."
											: "No language models detected. Configure a provider first."
									}
									value={settings.agent?.llm_model || ""}
									onValueChange={handleModelChange}
									defaultOpen={openLlmSelector}
								/>
							</LabelWrapper>
						</div>
						<div className="space-y-2">
							<LabelWrapper label="Agent Instructions" id="system-prompt">
								<Textarea
									id="system-prompt"
									placeholder="Enter your agent instructions here..."
									value={systemPrompt}
									onChange={(e) => setSystemPrompt(e.target.value)}
									rows={6}
									className={`resize-none ${
										systemPrompt.length > MAX_SYSTEM_PROMPT_CHARS
											? "!border-destructive focus:border-destructive"
											: ""
									}`}
								/>
							</LabelWrapper>
							<span
								className={`text-xs ${
									systemPrompt.length > MAX_SYSTEM_PROMPT_CHARS
										? "text-destructive"
										: "text-muted-foreground"
								}`}
							>
								{systemPrompt.length}/{MAX_SYSTEM_PROMPT_CHARS} characters
							</span>
						</div>
						<div className="flex justify-end pt-2">
							<Button
								onClick={handleSystemPromptSave}
								disabled={
									updateSettingsMutation.isPending ||
									systemPrompt.length > MAX_SYSTEM_PROMPT_CHARS
								}
								className="min-w-[120px]"
								size="sm"
								variant="outline"
							>
								{updateSettingsMutation.isPending ? (
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
					<div className="flex items-center justify-between mb-3">
						<CardTitle className="text-lg">Knowledge Ingest</CardTitle>
						<div className="flex gap-2">
							<ConfirmationDialog
								trigger={
									<Button ignoreTitleCase={true} variant="outline">
										Restore flow
									</Button>
								}
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
								description={
									<>
										<p className="mb-2">
											You&apos;re entering Langflow. You can edit the{" "}
											<b>Ingest flow</b> and other underlying flows. Manual
											changes to components, wiring, or I/O can break this
											experience.
										</p>
										<p className="mb-2">
											To enable editing, you need to unlock the flow by clicking
											on its name and disabling the <b>Lock flow</b> option.
										</p>
										<p>You can restore this flow from Settings.</p>
									</>
								}
								confirmText="Proceed"
								confirmIcon={<ArrowUpRight />}
								variant="warning"
								onConfirm={(closeDialog) =>
									handleEditInLangflow("ingest", closeDialog)
								}
							/>
						</div>
					</div>
					<CardDescription>
						Configure how files are ingested and stored for retrieval. Edit in
						Langflow for full control.
					</CardDescription>
				</CardHeader>
				<CardContent>
					<div className="space-y-6">
						<div className="space-y-2">
							<LabelWrapper
								helperText="Model used for knowledge ingest and retrieval"
								id="embedding-model-select"
								label="Embedding model"
								required={true}
							>
								<ModelSelector
									groupedOptions={groupedEmbeddingModels}
									noOptionsPlaceholder={
										isLoadingAnyEmbeddingModels
											? "Loading models..."
											: "No embedding models detected. Configure a provider first."
									}
									value={settings.knowledge?.embedding_model || ""}
									onValueChange={handleEmbeddingModelChange}
								/>
							</LabelWrapper>
						</div>
						<div className="grid grid-cols-2 gap-4">
							<div className="space-y-2">
								<LabelWrapper id="chunk-size" label="Chunk size">
									<div className="relative [&:has(input:hover):not(:has(input:focus))_button]:border-muted-foreground [&:has(input:focus)_button]:border-foreground">
										<Input
											id="chunk-size"
											type="number"
											min="1"
											value={chunkSize}
											onChange={(e) => handleChunkSizeChange(e.target.value)}
											className="w-full pr-20 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
										/>
										<div className="absolute inset-y-0 right-0 flex items-center">
											<span className="text-sm text-placeholder-foreground mr-4 pointer-events-none">
												characters
											</span>
											<div className="flex flex-col">
												<Button
													aria-label="Increase value"
													className="h-5 rounded-l-none rounded-br-none border-input border-b-[0.5px] focus-visible:relative transition-colors"
													variant="outline"
													size="iconSm"
													onClick={() =>
														handleChunkSizeChange((chunkSize + 1).toString())
													}
												>
													<Plus className="text-muted-foreground" size={8} />
												</Button>
												<Button
													aria-label="Decrease value"
													className="h-5 rounded-l-none rounded-tr-none border-input border-t-[0.5px] focus-visible:relative transition-colors"
													variant="outline"
													size="iconSm"
													onClick={() =>
														handleChunkSizeChange((chunkSize - 1).toString())
													}
												>
													<Minus className="text-muted-foreground" size={8} />
												</Button>
											</div>
										</div>
									</div>
								</LabelWrapper>
							</div>
							<div className="space-y-2">
								<LabelWrapper id="chunk-overlap" label="Chunk overlap">
									<div className="relative [&:has(input:hover):not(:has(input:focus))_button]:border-muted-foreground [&:has(input:focus)_button]:border-foreground">
										<Input
											id="chunk-overlap"
											type="number"
											min="0"
											value={chunkOverlap}
											onChange={(e) => handleChunkOverlapChange(e.target.value)}
											className="w-full pr-20 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
										/>
										<div className="absolute inset-y-0 right-0 flex items-center">
											<span className="text-sm text-placeholder-foreground mr-4 pointer-events-none">
												characters
											</span>
											<div className="flex flex-col">
												<Button
													aria-label="Increase value"
													className="h-5 rounded-l-none rounded-br-none border-input border-b-[0.5px] focus-visible:relative transition-colors"
													variant="outline"
													size="iconSm"
													onClick={() =>
														handleChunkOverlapChange(
															(chunkOverlap + 1).toString(),
														)
													}
												>
													<Plus className="text-muted-foreground" size={8} />
												</Button>
												<Button
													aria-label="Decrease value"
													className="h-5 rounded-l-none rounded-tr-none border-input border-t-[0.5px] focus-visible:relative transition-colors"
													variant="outline"
													size="iconSm"
													onClick={() =>
														handleChunkOverlapChange(
															(chunkOverlap - 1).toString(),
														)
													}
												>
													<Minus className="text-muted-foreground" size={8} />
												</Button>
											</div>
										</div>
									</div>
								</LabelWrapper>
							</div>
						</div>
						<div className="">
							<div className="flex items-center justify-between py-3 border-b border-border">
								<div className="flex-1">
									<Label
										htmlFor="table-structure"
										className="text-base font-medium cursor-pointer pb-3"
									>
										Table Structure
									</Label>
									<div className="text-sm text-muted-foreground">
										Capture table structure during ingest.
									</div>
								</div>
								<Switch
									id="table-structure"
									checked={tableStructure}
									onCheckedChange={handleTableStructureChange}
								/>
							</div>
							<div className="flex items-center justify-between py-3 border-b border-border">
								<div className="flex-1">
									<Label
										htmlFor="ocr"
										className="text-base font-medium cursor-pointer pb-3"
									>
										OCR
									</Label>
									<div className="text-sm text-muted-foreground">
										Extracts text from images/PDFs. Ingest is slower when
										enabled.
									</div>
								</div>
								<Switch
									id="ocr"
									checked={ocr}
									onCheckedChange={handleOcrChange}
								/>
							</div>
							<div className="flex items-center justify-between py-3">
								<div className="flex-1">
									<Label
										htmlFor="picture-descriptions"
										className="text-base font-medium cursor-pointer pb-3"
									>
										Picture Descriptions
									</Label>
									<div className="text-sm text-muted-foreground">
										Adds captions for images. Ingest is slower when enabled.
									</div>
								</div>
								<Switch
									id="picture-descriptions"
									checked={pictureDescriptions}
									onCheckedChange={handlePictureDescriptionsChange}
								/>
							</div>
						</div>
					</div>
				</CardContent>
			</Card>
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
