"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
	type OnboardingVariables,
	useOnboardingMutation,
} from "@/app/api/mutations/useOnboardingMutation";
import { useGetTasksQuery } from "@/app/api/queries/useGetTasksQuery";
import { useDoclingHealth } from "@/components/docling-health-banner";
import IBMLogo from "@/components/logo/ibm-logo";
import OllamaLogo from "@/components/logo/ollama-logo";
import OpenAILogo from "@/components/logo/openai-logo";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
	Tooltip,
	TooltipContent,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { AnimatedProviderSteps } from "./animated-provider-steps";
import { IBMOnboarding } from "./ibm-onboarding";
import { OllamaOnboarding } from "./ollama-onboarding";
import { OpenAIOnboarding } from "./openai-onboarding";

interface OnboardingCardProps {
	onComplete: () => void;
	setIsLoadingModels?: (isLoading: boolean) => void;
	setLoadingStatus?: (status: string[]) => void;
}


const STEP_LIST = [
  "Setting up your model provider",
  "Defining schema",
  "Configuring Langflow",
  "Ingesting sample data",
];

const TOTAL_PROVIDER_STEPS = STEP_LIST.length;

const OnboardingCard = ({
	onComplete,
	setIsLoadingModels: setIsLoadingModelsParent,
	setLoadingStatus: setLoadingStatusParent,
}: OnboardingCardProps) => {
	const { isHealthy: isDoclingHealthy } = useDoclingHealth();

	const [modelProvider, setModelProvider] = useState<string>("openai");

	const [sampleDataset, setSampleDataset] = useState<boolean>(true);

	const [isLoadingModels, setIsLoadingModels] = useState<boolean>(false);

	const [loadingStatus, setLoadingStatus] = useState<string[]>([]);

	const [currentStatusIndex, setCurrentStatusIndex] = useState<number>(0);

	// Pass loading state to parent
	useEffect(() => {
		setIsLoadingModelsParent?.(isLoadingModels);
	}, [isLoadingModels, setIsLoadingModelsParent]);

	useEffect(() => {
		setLoadingStatusParent?.(loadingStatus);
	}, [loadingStatus, setLoadingStatusParent]);

	// Cycle through loading status messages once
	useEffect(() => {
		if (!isLoadingModels || loadingStatus.length === 0) {
			setCurrentStatusIndex(0);
			return;
		}

		const interval = setInterval(() => {
			setCurrentStatusIndex((prev) => {
				const nextIndex = prev + 1;
				// Stop at the last message
				if (nextIndex >= loadingStatus.length - 1) {
					clearInterval(interval);
					return loadingStatus.length - 1;
				}
				return nextIndex;
			});
		}, 1500); // Change status every 1.5 seconds

		return () => clearInterval(interval);
	}, [isLoadingModels, loadingStatus]);

	const handleSetModelProvider = (provider: string) => {
		setModelProvider(provider);
		setSettings({
			model_provider: provider,
			embedding_model: "",
			llm_model: "",
		});
	};

	const [settings, setSettings] = useState<OnboardingVariables>({
		model_provider: modelProvider,
		embedding_model: "",
		llm_model: "",
	});

	const [currentStep, setCurrentStep] = useState<number | null>(null);

	// Query tasks to track completion
	const { data: tasks } = useGetTasksQuery({
		enabled: currentStep !== null, // Only poll when onboarding has started
		refetchInterval: currentStep !== null ? 1000 : false, // Poll every 1 second during onboarding
	});

	// Monitor tasks and call onComplete when all tasks are done
	useEffect(() => {
		if (currentStep === null || !tasks) {
			return;
		}

		// Check if there are any active tasks (pending, running, or processing)
		const activeTasks = tasks.find(
			(task) =>
				task.status === "pending" ||
				task.status === "running" ||
				task.status === "processing",
		);

		// If no active tasks and we've started onboarding, complete it
		if (
			(!activeTasks || (activeTasks.processed_files ?? 0) > 0) &&
			tasks.length > 0
		) {
			// Set to final step to show "Done"
			setCurrentStep(TOTAL_PROVIDER_STEPS);
			// Wait a bit before completing
			setTimeout(() => {
				onComplete();
			}, 1000);
		}
	}, [tasks, currentStep, onComplete]);

	// Mutations
	const onboardingMutation = useOnboardingMutation({
		onSuccess: (data) => {
			console.log("Onboarding completed successfully", data);
			setCurrentStep(0);
		},
		onError: (error) => {
			toast.error("Failed to complete onboarding", {
				description: error.message,
			});
		},
	});

	const handleComplete = () => {
		if (
			!settings.model_provider ||
			!settings.llm_model ||
			!settings.embedding_model
		) {
			toast.error("Please complete all required fields");
			return;
		}

		// Prepare onboarding data
		const onboardingData: OnboardingVariables = {
			model_provider: settings.model_provider,
			llm_model: settings.llm_model,
			embedding_model: settings.embedding_model,
			sample_data: sampleDataset,
		};

		// Add API key if available
		if (settings.api_key) {
			onboardingData.api_key = settings.api_key;
		}

		// Add endpoint if available
		if (settings.endpoint) {
			onboardingData.endpoint = settings.endpoint;
		}

		// Add project_id if available
		if (settings.project_id) {
			onboardingData.project_id = settings.project_id;
		}

		onboardingMutation.mutate(onboardingData);
		setCurrentStep(0);
	};

	const isComplete =
		!!settings.llm_model && !!settings.embedding_model && isDoclingHealthy;

	return (
		<AnimatePresence mode="wait">
			{currentStep === null ? (
				<motion.div
					key="onboarding-form"
					initial={{ opacity: 1, y: 0 }}
					exit={{ opacity: 0, y: -24 }}
					transition={{ duration: 0.4, ease: "easeInOut" }}
				>
					<div className={`w-full max-w-[600px] flex flex-col gap-6`}>
						<Tabs
							defaultValue={modelProvider}
							onValueChange={handleSetModelProvider}
						>
							<TabsList className="mb-4">
								<TabsTrigger
									value="openai"
								>
									<div className={cn("flex items-center justify-center gap-2 w-8 h-8 rounded-md", modelProvider === "openai" ? "bg-white" : "bg-muted")}>
										<OpenAILogo className={cn("w-4 h-4 shrink-0", modelProvider === "openai" ? "text-black" : "text-muted-foreground")} />
									</div>
									OpenAI
								</TabsTrigger>
								<TabsTrigger
									value="watsonx"
								>
									<div className={cn("flex items-center justify-center gap-2 w-8 h-8 rounded-md", modelProvider === "watsonx" ? "bg-[#1063FE]" : "bg-muted")}>
										<IBMLogo className={cn("w-4 h-4 shrink-0", modelProvider === "watsonx" ? "text-white" : "text-muted-foreground")} />
									</div>
									IBM watsonx.ai
								</TabsTrigger>
								<TabsTrigger
									value="ollama"
								>
									<div className={cn("flex items-center justify-center gap-2 w-8 h-8 rounded-md", modelProvider === "ollama" ? "bg-white" : "bg-muted")}>
										<OllamaLogo
											className={cn(
												"w-4 h-4 shrink-0",
												modelProvider === "ollama" ? "text-black" : "text-muted-foreground",
											)}
										/>
									</div>
									Ollama
								</TabsTrigger>
							</TabsList>
							<TabsContent value="openai">
								<OpenAIOnboarding
									setSettings={setSettings}
									sampleDataset={sampleDataset}
									setSampleDataset={setSampleDataset}
									setIsLoadingModels={setIsLoadingModels}
									setLoadingStatus={setLoadingStatus}
								/>
							</TabsContent>
							<TabsContent value="watsonx">
								<IBMOnboarding
									setSettings={setSettings}
									sampleDataset={sampleDataset}
									setSampleDataset={setSampleDataset}
									setIsLoadingModels={setIsLoadingModels}
									setLoadingStatus={setLoadingStatus}
								/>
							</TabsContent>
							<TabsContent value="ollama">
								<OllamaOnboarding
									setSettings={setSettings}
									sampleDataset={sampleDataset}
									setSampleDataset={setSampleDataset}
									setIsLoadingModels={setIsLoadingModels}
									setLoadingStatus={setLoadingStatus}
								/>
							</TabsContent>
						</Tabs>

						{!isLoadingModels && (
							<Tooltip>
								<TooltipTrigger asChild>
									<div>
										<Button
											size="sm"
											onClick={handleComplete}
											disabled={!isComplete}
											loading={onboardingMutation.isPending}
										>
											<span className="select-none">Complete</span>
										</Button>
									</div>
								</TooltipTrigger>
								{!isComplete && (
									<TooltipContent>
										{!!settings.llm_model &&
										!!settings.embedding_model &&
										!isDoclingHealthy
											? "docling-serve must be running to continue"
											: "Please fill in all required fields"}
									</TooltipContent>
								)}
							</Tooltip>
						)}
					</div>
				</motion.div>
			) : (
				<motion.div
					key="provider-steps"
					initial={{ opacity: 0, y: 24 }}
					animate={{ opacity: 1, y: 0 }}
					transition={{ duration: 0.4, ease: "easeInOut" }}
				>
					<AnimatedProviderSteps
            currentStep={currentStep}
            setCurrentStep={setCurrentStep}
            steps={STEP_LIST}
          />
				</motion.div>
			)}
		</AnimatePresence>
	);
};

export default OnboardingCard;
