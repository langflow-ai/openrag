"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Loader2, PlugZap, RefreshCw } from "lucide-react";
import { ProtectedRoute } from "@/components/protected-route";
import { useTask } from "@/contexts/task-context";
import { useAuth } from "@/contexts/auth-context";

interface Connector {
	id: string;
	name: string;
	description: string;
	icon: React.ReactNode;
	status: "not_connected" | "connecting" | "connected" | "error";
	type: string;
	connectionId?: string;
	access_token?: string;
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

	// Settings state
	// Note: backend internal Langflow URL is not needed on the frontend
	const [flowId, setFlowId] = useState<string>(
		"1098eea1-6649-4e1d-aed1-b77249fb8dd0",
	);
	const [ingestFlowId, setIngestFlowId] = useState<string>("");
	const [langflowEditUrl, setLangflowEditUrl] = useState<string>("");
	const [langflowIngestEditUrl, setLangflowIngestEditUrl] =
		useState<string>("");
	const [publicLangflowUrl, setPublicLangflowUrl] = useState<string>("");

	// Ingestion settings state - will be populated from Langflow flow defaults
	const [ingestionSettings, setIngestionSettings] = useState({
		chunkSize: 1000,
		chunkOverlap: 200,
		separator: "\\n",
		embeddingModel: "text-embedding-3-small",
	});
	const [settingsLoaded, setSettingsLoaded] = useState(false);

	// Fetch settings from backend
	const fetchSettings = useCallback(async () => {
		try {
			const response = await fetch("/api/settings");
			if (response.ok) {
				const settings = await response.json();
				if (settings.flow_id) {
					setFlowId(settings.flow_id);
				}
				if (settings.ingest_flow_id) {
					console.log("Setting ingestFlowId to:", settings.ingest_flow_id);
					setIngestFlowId(settings.ingest_flow_id);
				} else {
					console.log("No ingest_flow_id in settings:", settings);
				}
				if (settings.langflow_edit_url) {
					setLangflowEditUrl(settings.langflow_edit_url);
				}
				if (settings.langflow_ingest_edit_url) {
					setLangflowIngestEditUrl(settings.langflow_ingest_edit_url);
				}
				if (settings.langflow_public_url) {
					setPublicLangflowUrl(settings.langflow_public_url);
				}
				if (settings.ingestion_defaults) {
					console.log(
						"Loading ingestion defaults from backend:",
						settings.ingestion_defaults,
					);
					setIngestionSettings(settings.ingestion_defaults);
					setSettingsLoaded(true);
				}
			}
		} catch (error) {
			console.error("Failed to fetch settings:", error);
		}
	}, []);

	// Helper function to get connector icon
	const getConnectorIcon = (iconName: string) => {
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
	};

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
	}, []);

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
						`redirect_uri=${encodeURIComponent(result.oauth_config.redirect_uri)}&` +
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
			const response = await fetch(`/api/connectors/${connector.type}/sync`, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
				},
				body: JSON.stringify({
					connection_id: connector.connectionId,
					max_files: syncAllFiles ? 0 : maxFiles || undefined,
				}),
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

	// Fetch settings on mount when authenticated
	useEffect(() => {
		if (isAuthenticated) {
			fetchSettings();
		}
	}, [isAuthenticated, fetchSettings]);

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

	return (
		<div className="space-y-8">
			{/* Agent Behavior Section */}
			<div className="flex items-center justify-between py-4">
				<div>
					<h3 className="text-lg font-medium">Agent behavior</h3>
					<p className="text-sm text-muted-foreground">
						Adjust your retrieval agent flow
					</p>
				</div>
				<Button
					onClick={() => {
						const derivedFromWindow =
							typeof window !== "undefined"
								? `${window.location.protocol}//${window.location.hostname}:7860`
								: "";
						const base = (
							publicLangflowUrl ||
							derivedFromWindow ||
							"http://localhost:7860"
						).replace(/\/$/, "");
						const computed = flowId ? `${base}/flow/${flowId}` : base;
						const url = langflowEditUrl || computed;
						window.open(url, "_blank");
					}}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="24"
						height="22"
						viewBox="0 0 24 22"
						className="h-4 w-4 mr-2"
					>
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
			</div>

			{/* Ingest Flow Section */}
			<div className="flex items-center justify-between py-4">
				<div>
					<h3 className="text-lg font-medium">File ingestion</h3>
					<p className="text-sm text-muted-foreground">
						Customize your file processing and indexing flow
					</p>
				</div>
				<Button
					onClick={() => {
						const derivedFromWindow =
							typeof window !== "undefined"
								? `${window.location.protocol}//${window.location.hostname}:7860`
								: "";
						const base = (
							publicLangflowUrl ||
							derivedFromWindow ||
							"http://localhost:7860"
						).replace(/\/$/, "");
						const computed = ingestFlowId
							? `${base}/flow/${ingestFlowId}`
							: base;
						const url = langflowIngestEditUrl || computed;
						window.open(url, "_blank");
					}}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="24"
						height="22"
						viewBox="0 0 24 22"
						className="h-4 w-4 mr-2"
					>
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
			</div>

			{/* Ingestion Settings Section */}
			<div className="space-y-4">
				<div>
					<h3 className="text-lg font-medium">Ingestion settings</h3>
					<p className="text-sm text-muted-foreground">
						Configure how your documents are processed and indexed
					</p>
				</div>

				<div className="grid gap-6 md:grid-cols-2">
					<Card>
						<CardHeader>
							<CardTitle className="text-base">Document Processing</CardTitle>
							<CardDescription>
								Control how text is split and processed
							</CardDescription>
						</CardHeader>
						<CardContent className="space-y-4">
							<div className="space-y-2">
								<Label htmlFor="chunkSize">Chunk Size</Label>
								<Input
									id="chunkSize"
									type="number"
									value={ingestionSettings.chunkSize}
									onChange={(e) =>
										setIngestionSettings((prev) => ({
											...prev,
											chunkSize: parseInt(e.target.value) || 1000,
										}))
									}
									min="100"
									max="4000"
								/>
								<p className="text-xs text-muted-foreground">
									Maximum characters per text chunk (100-4000)
								</p>
							</div>

							<div className="space-y-2">
								<Label htmlFor="chunkOverlap">Chunk Overlap</Label>
								<Input
									id="chunkOverlap"
									type="number"
									value={ingestionSettings.chunkOverlap}
									onChange={(e) =>
										setIngestionSettings((prev) => ({
											...prev,
											chunkOverlap: parseInt(e.target.value) || 200,
										}))
									}
									min="0"
									max="500"
								/>
								<p className="text-xs text-muted-foreground">
									Character overlap between chunks (0-500)
								</p>
							</div>
						</CardContent>
					</Card>

					<Card>
						<CardHeader>
							<CardTitle className="text-base">Embeddings</CardTitle>
							<CardDescription>
								Configure embedding model and search behavior
							</CardDescription>
						</CardHeader>
						<CardContent className="space-y-4">
							<div className="space-y-2">
								<Label htmlFor="embeddingModel">Embedding Model</Label>
								<select
									id="embeddingModel"
									value={ingestionSettings.embeddingModel}
									onChange={(e) =>
										setIngestionSettings((prev) => ({
											...prev,
											embeddingModel: e.target.value,
										}))
									}
									className="w-full px-3 py-2 border border-input bg-background text-foreground rounded-md text-sm"
								>
									<option value="text-embedding-3-small">
										text-embedding-3-small (fast, cheaper)
									</option>
									<option value="text-embedding-3-large">
										text-embedding-3-large (better quality)
									</option>
									<option value="text-embedding-ada-002">
										text-embedding-ada-002 (legacy)
									</option>
								</select>
							</div>

						</CardContent>
					</Card>
				</div>
			</div>

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
