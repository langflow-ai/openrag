import { useEffect, useState } from "react";
import { LabelInput } from "@/components/label-input";
import { LabelWrapper } from "@/components/label-wrapper";
import OpenAILogo from "@/components/logo/openai-logo";
import { Switch } from "@/components/ui/switch";
import { useDebouncedValue } from "@/lib/debounce";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { useGetOpenAIModelsQuery } from "../../api/queries/useGetModelsQuery";
import { useModelSelection } from "../hooks/useModelSelection";
import { useUpdateSettings } from "../hooks/useUpdateSettings";
import { AdvancedOnboarding } from "./advanced";

export function OpenAIOnboarding({
	setSettings,
	sampleDataset,
	setSampleDataset,
	setIsLoadingModels,
}: {
	setSettings: (settings: OnboardingVariables) => void;
	sampleDataset: boolean;
	setSampleDataset: (dataset: boolean) => void;
	setIsLoadingModels?: (isLoading: boolean) => void;
}) {
	const [apiKey, setApiKey] = useState("");
	const [getFromEnv, setGetFromEnv] = useState(true);
	const debouncedApiKey = useDebouncedValue(apiKey, 500);

	// Fetch models from API when API key is provided
	const {
		data: modelsData,
		isLoading: isLoadingModels,
		error: modelsError,
	} = useGetOpenAIModelsQuery(
		getFromEnv
			? { apiKey: "" }
			: debouncedApiKey
				? { apiKey: debouncedApiKey }
				: undefined,
		{ enabled: debouncedApiKey !== "" || getFromEnv },
	);
	// Use custom hook for model selection logic
	const {
		languageModel,
		embeddingModel,
		setLanguageModel,
		setEmbeddingModel,
		languageModels,
		embeddingModels,
	} = useModelSelection(modelsData);
	const handleSampleDatasetChange = (dataset: boolean) => {
		setSampleDataset(dataset);
	};

	const handleGetFromEnvChange = (fromEnv: boolean) => {
		setGetFromEnv(fromEnv);
		if (fromEnv) {
			setApiKey("");
		}
		setLanguageModel("");
		setEmbeddingModel("");
	};

	useEffect(() => {
		setIsLoadingModels?.(isLoadingModels);
	}, [isLoadingModels, setIsLoadingModels]);

	// Update settings when values change
	useUpdateSettings(
		"openai",
		{
			apiKey,
			languageModel,
			embeddingModel,
		},
		setSettings,
	);
	
	return (
		<>
			<div className="space-y-5">
				<LabelWrapper
					label="Use environment OpenAI API key"
					id="get-api-key"
					description="Reuse the key from your environment config. Turn off to enter a different key."
					flex
				>
					<Switch
						checked={getFromEnv}
						onCheckedChange={handleGetFromEnvChange}
					/>
				</LabelWrapper>
				{!getFromEnv && (
					<div className="space-y-1">
						<LabelInput
							label="OpenAI API key"
							helperText="The API key for your OpenAI account."
							className={modelsError ? "!border-destructive" : ""}
							id="api-key"
							type="password"
							required
							placeholder="sk-..."
							value={apiKey}
							onChange={(e) => setApiKey(e.target.value)}
						/>
						{isLoadingModels && (
							<p className="text-mmd text-muted-foreground">
								Validating API key...
							</p>
						)}
						{modelsError && (
							<p className="text-mmd text-destructive">
								Invalid OpenAI API key. Verify or replace the key.
							</p>
						)}
					</div>
				)}
			</div>
			<AdvancedOnboarding
				icon={<OpenAILogo className="w-4 h-4" />}
				languageModels={languageModels}
				embeddingModels={embeddingModels}
				languageModel={languageModel}
				embeddingModel={embeddingModel}
				sampleDataset={sampleDataset}
				setLanguageModel={setLanguageModel}
				setSampleDataset={handleSampleDatasetChange}
				setEmbeddingModel={setEmbeddingModel}
			/>
		</>
	);
}
