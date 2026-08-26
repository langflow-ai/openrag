"use client";

import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  type OnboardingVariables,
  useOnboardingMutation,
} from "@/app/api/mutations/useOnboardingMutation";
import { useOnboardingRollbackMutation } from "@/app/api/mutations/useOnboardingRollbackMutation";
import { useGetModelProvidersQuery } from "@/app/api/queries/useGetModelProvidersQuery";
import { useGetModelCatalogQuery } from "@/app/api/queries/useGetModelsQuery";
import {
  type ProviderSettings,
  useGetSettingsQuery,
} from "@/app/api/queries/useGetSettingsQuery";
import { useGetTasksQuery } from "@/app/api/queries/useGetTasksQuery";
import type { ProviderHealthResponse } from "@/app/api/queries/useProviderHealthQuery";
import {
  EMBEDDING_PROVIDER_ORDER,
  getProviderChrome,
  LLM_PROVIDER_ORDER,
  orderProviders,
} from "@/app/settings/_helpers/model-helpers";
import { useDoclingHealth } from "@/components/docling-health-banner";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  trackButton,
  trackProcessFailure,
  trackProcessSuccess,
} from "@/lib/analytics";
import { formatProviderErrorMessage } from "@/lib/chat-stream-errors";
import { cn } from "@/lib/utils";
import { AnimatedProviderSteps } from "./animated-provider-steps";
import { AnthropicOnboarding } from "./anthropic-onboarding";
import { GenericOnboarding } from "./generic-onboarding";
import { IBMOnboarding } from "./ibm-onboarding";
import { OllamaOnboarding } from "./ollama-onboarding";
import { OpenAIOnboarding } from "./openai-onboarding";
import { TabTrigger } from "./tab-trigger";

interface OnboardingCardProps {
  onComplete: () => void;
  isCompleted?: boolean;
  isEmbedding?: boolean;
}

const STEP_LIST = [
  "Setting up your model provider",
  "Defining schema",
  "Configuring Langflow",
];

// Providers whose model inventory is read live from the running service, so an
// empty catalogue list says nothing about what they can serve.
const LIVE_MODEL_PROVIDERS = new Set(["ollama", "watsonx"]);

const EMBEDDING_STEP_LIST = [
  "Setting up your model provider",
  "Defining schema",
  "Configuring Langflow",
  "Ingesting sample data",
];

const OnboardingCard = ({
  onComplete,
  isEmbedding = false,
  isCompleted = false,
}: OnboardingCardProps) => {
  const { isHealthy: isDoclingHealthy } = useDoclingHealth();

  // Which providers this deployment offers comes from the backend, filtered by
  // OPENRAG_RUN_MODE (config/model_providers.yaml). Onboarding renders that
  // list; it does not decide availability from the UI brand.
  const { data: providerData } = useGetModelProvidersQuery();
  const availableProviders = useMemo(
    () => providerData?.providers ?? [],
    [providerData],
  );
  const providerDisplayNames = useMemo(
    () =>
      Object.fromEntries(
        availableProviders.map(({ name, display_name }) => [
          name,
          display_name,
        ]),
      ),
    [availableProviders],
  );
  const providerKeys = useMemo(
    () =>
      orderProviders(
        availableProviders.map((provider) => provider.name),
        isEmbedding ? EMBEDDING_PROVIDER_ORDER : LLM_PROVIDER_ORDER,
      ),
    [availableProviders, isEmbedding],
  );

  const { data: catalog } = useGetModelCatalogQuery();

  // The embedding step must not offer a provider that serves no embedding
  // models — Anthropic being the standing example. The catalogue answers that
  // for every provider except the two whose inventory comes from the running
  // server rather than LiteLLM's bundled list.
  const tabProviders = useMemo(() => {
    if (!isEmbedding) {
      return providerKeys;
    }
    return providerKeys.filter((providerKey) => {
      if (LIVE_MODEL_PROVIDERS.has(providerKey)) {
        return true;
      }
      const entry = catalog?.providers?.find(
        (item) => item.key === providerKey,
      );
      // Catalogue not loaded yet: hide nothing rather than flicker tabs away.
      return !entry || entry.embedding_models.length > 0;
    });
  }, [providerKeys, isEmbedding, catalog]);

  const [modelProvider, setModelProvider] = useState<string>(
    isEmbedding ? "openai" : "anthropic",
  );

  // The default above may not be offered here (Anthropic disabled, or the
  // embedding step). Fall back to the first provider this step does offer.
  const [prevTabProviders, setPrevTabProviders] = useState<string[]>([]);
  if (tabProviders !== prevTabProviders && tabProviders.length > 0) {
    setPrevTabProviders(tabProviders);
    if (!tabProviders.includes(modelProvider)) {
      setModelProvider(tabProviders[0]);
    }
  }

  // Read model-fetch loading from React Query instead of syncing it up from children.
  const isLoadingModels = useIsFetching({ queryKey: ["models"] }) > 0;

  const queryClient = useQueryClient();

  // Fetch current settings to check if providers are already configured
  const { data: currentSettings } = useGetSettingsQuery();

  // Auto-select the first provider that has an API key set in env vars
  const [prevProviders, setPrevProviders] = useState<
    ProviderSettings | undefined | null
  >(null);
  if (currentSettings?.providers !== prevProviders) {
    setPrevProviders(currentSettings?.providers);
    if (currentSettings?.providers) {
      for (const provider of tabProviders) {
        if (
          provider === "anthropic" &&
          currentSettings.providers.anthropic?.has_api_key
        ) {
          setModelProvider("anthropic");
          break;
        } else if (
          provider === "openai" &&
          currentSettings.providers.openai?.has_api_key
        ) {
          setModelProvider("openai");
          break;
        } else if (
          provider === "watsonx" &&
          currentSettings.providers.watsonx?.has_api_key
        ) {
          setModelProvider("watsonx");
          break;
        } else if (
          provider === "ollama" &&
          currentSettings.providers.ollama?.endpoint
        ) {
          setModelProvider("ollama");
          break;
        } else if (
          currentSettings.providers.custom?.[provider]?.configured === true
        ) {
          setModelProvider(provider);
          break;
        }
      }
    }
  }

  const handleSetModelProvider = (provider: string) => {
    setModelProvider(provider);
    setSettings({
      [isEmbedding ? "embedding_provider" : "llm_provider"]: provider,
      embedding_model: "",
      llm_model: "",
    });
    setError(null);
  };

  // Check if the selected provider is already configured
  const isProviderAlreadyConfigured = (provider: string): boolean => {
    if (!isEmbedding || !currentSettings?.providers) return false;

    // Check if provider has been explicitly configured (not just from env vars)
    if (provider === "openai") {
      return currentSettings.providers.openai?.configured === true;
    } else if (provider === "anthropic") {
      return currentSettings.providers.anthropic?.configured === true;
    } else if (provider === "watsonx") {
      return currentSettings.providers.watsonx?.configured === true;
    } else if (provider === "ollama") {
      return currentSettings.providers.ollama?.configured === true;
    }
    return currentSettings.providers.custom?.[provider]?.configured === true;
  };

  const showProviderConfiguredMessage =
    isProviderAlreadyConfigured(modelProvider);
  const providerAlreadyConfigured =
    isEmbedding && showProviderConfiguredMessage;

  const totalSteps = isEmbedding
    ? EMBEDDING_STEP_LIST.length
    : STEP_LIST.length;

  const [settings, setSettings] = useState<OnboardingVariables>({
    [isEmbedding ? "embedding_provider" : "llm_provider"]: modelProvider,
    embedding_model: "",
    llm_model: "",
    // Provider-specific fields will be set by provider components
    openai_api_key: "",
    anthropic_api_key: "",
    watsonx_api_key: "",
    watsonx_endpoint: "",
    watsonx_project_id: "",
    ollama_endpoint: "",
  });

  const [currentStep, setCurrentStep] = useState<number | null>(
    isCompleted ? totalSteps : null,
  );

  const [processingStartTime, setProcessingStartTime] = useState<number | null>(
    null,
  );

  const [error, setError] = useState<string | null>(null);

  const [onboardingTaskId, setOnboardingTaskId] = useState<string | null>(null);

  // Track which tasks we've already handled to prevent infinite loops
  const handledFailedTasksRef = useRef<Set<string>>(new Set());

  // Delay calling onComplete so the "Done" step is briefly visible.
  const [pendingComplete, setPendingComplete] = useState(false);
  const onCompleteEvent = useEffectEvent(onComplete);
  useEffect(() => {
    if (!pendingComplete) {
      return;
    }
    const timeoutId = setTimeout(() => {
      onCompleteEvent();
      setPendingComplete(false);
    }, 1000);
    return () => clearTimeout(timeoutId);
  }, [pendingComplete]);

  // Query tasks to track completion
  const { data: tasks } = useGetTasksQuery({
    enabled: currentStep !== null && !isCompleted, // Only poll when onboarding has started and stop once step is complete
    refetchInterval: currentStep !== null ? 1000 : false, // Poll every 1 second during onboarding
  });

  // Rollback mutation
  const rollbackMutation = useOnboardingRollbackMutation({
    onSuccess: () => {
      // Reset to provider selection step
      // Error message is already set before calling mutate
      setCurrentStep(null);
    },
    onError: (error) => {
      console.error("Failed to rollback onboarding", error);
      // Preserve existing error message if set, otherwise show rollback error
      setError(
        (prevError) => prevError || `Failed to rollback: ${error.message}`,
      );
      // Still reset to provider selection even if rollback fails
      setCurrentStep(null);
    },
  });

  // Mutations
  const onboardingMutation = useOnboardingMutation({
    onSuccess: (data) => {
      if (data.task_id) {
        setOnboardingTaskId(data.task_id);
      }

      // Update provider health cache to healthy since backend just validated
      const provider =
        (isEmbedding ? settings.embedding_provider : settings.llm_provider) ||
        modelProvider;
      const healthData: ProviderHealthResponse = {
        status: "healthy",
        message: "Provider is configured and working correctly",
        provider: provider,
      };
      queryClient.setQueryData(["provider", "health"], healthData);
      setError(null);
      if (!isEmbedding) {
        trackProcessSuccess({
          processType: "Onboarding",
          process: "LLM Setup",
          resultValue: provider,
          category: "Setup",
        });
        setCurrentStep(totalSteps);
        setPendingComplete(true);
      } else {
        trackProcessSuccess({
          processType: "Onboarding",
          process: "Embedding Setup",
          resultValue: provider,
          category: "Setup",
        });
        setCurrentStep(0);
      }
    },
    onError: (error) => {
      const message = formatProviderErrorMessage(error.message);
      trackProcessFailure({
        processType: "Onboarding",
        process: isEmbedding ? "Embedding Setup" : "LLM Setup",
        resultValue: message,
        category: "Setup",
      });
      setError(message);
      setCurrentStep(totalSteps);
      rollbackMutation.mutate({ embedding_only: isEmbedding });
    },
  });

  // Monitor tasks and call onComplete when all tasks are done
  useEffect(() => {
    if (currentStep === null || !tasks || !isEmbedding) {
      return;
    }

    if (!onboardingMutation.isSuccess) {
      return;
    }

    const relevantTasks = onboardingTaskId
      ? tasks.filter((task) => task.task_id === onboardingTaskId)
      : [];

    // Check if there are any active tasks (pending, running, or processing)
    const activeTasks = relevantTasks.find(
      (task) =>
        task.status === "pending" ||
        task.status === "running" ||
        task.status === "processing",
    );

    // Check if any task failed at the top level
    const failedTask = relevantTasks.find(
      (task) => task.status === "failed" || task.status === "error",
    );

    // Check if any completed task has at least one failed file
    const completedTaskWithFailedFile = relevantTasks.find((task) => {
      // Must have files object
      if (!task.files || typeof task.files !== "object") {
        return false;
      }

      const fileEntries = Object.values(task.files);

      // Must have at least one file
      if (fileEntries.length === 0) {
        return false;
      }

      // Check if any file has failed status
      const hasFailedFile = fileEntries.some(
        (file) => file.status === "failed" || file.status === "error",
      );

      return hasFailedFile;
    });

    const taskWithFailure = failedTask || completedTaskWithFailedFile;

    // If any file failed, show error and jump back one step (like onboardingMutation.onError)
    // Only handle if we haven't already handled this task
    if (
      taskWithFailure &&
      !rollbackMutation.isPending &&
      !isCompleted &&
      !handledFailedTasksRef.current.has(taskWithFailure.task_id)
    ) {
      console.error("Task failed, jumping back one step", taskWithFailure);

      // Mark this task as handled to prevent infinite loops
      handledFailedTasksRef.current.add(taskWithFailure.task_id);

      // Prefer sanitized user_facing_message from enhanced tasks, then raw error.
      const errorMessages: string[] = [];
      if (taskWithFailure.files) {
        Object.values(taskWithFailure.files).forEach((file) => {
          if (file.status !== "failed" && file.status !== "error") {
            return;
          }
          const msg = file.user_facing_message || file.error;
          if (msg) {
            errorMessages.push(msg);
          }
        });
      }

      if (taskWithFailure.error) {
        errorMessages.push(taskWithFailure.error);
      }

      const errorMessage = formatProviderErrorMessage(
        errorMessages[0] || "Sample data ingestion failed. Please try again.",
      );

      trackProcessFailure({
        processType: "Onboarding",
        process: "Sample Data Ingest",
        resultValue: errorMessage,
        category: "Setup",
        task_id: taskWithFailure.task_id,
        duration_seconds: taskWithFailure.duration_seconds,
        total_files: taskWithFailure.total_files,
        failed_files: taskWithFailure.failed_files,
      });

      setPendingComplete(false);
      setError(errorMessage);
      setCurrentStep(totalSteps);
      rollbackMutation.mutate({ embedding_only: isEmbedding });
      return;
    }

    const hasSuccessfulTasks =
      relevantTasks.length > 0 &&
      (!activeTasks || (activeTasks.successful_files ?? 0) > 0);

    const hasIngestionDisabledOrDone =
      !onboardingTaskId && currentStep === totalSteps - 1;

    // If at least one processed file, no failures, and we've started onboarding, complete it
    if (
      (hasSuccessfulTasks || hasIngestionDisabledOrDone) &&
      !isCompleted &&
      !taskWithFailure &&
      currentStep === totalSteps - 1
    ) {
      const completedTask = relevantTasks.find((t) => t.status === "completed");
      trackProcessSuccess({
        processType: "Onboarding",
        process: "Sample Data Ingest",
        category: "Setup",
        task_id: completedTask?.task_id,
        duration_seconds: completedTask?.duration_seconds,
        total_files: completedTask?.total_files,
        successful_files: completedTask?.successful_files,
      });

      // Set to final step to show "Done", then delay onComplete via pendingComplete.
      setCurrentStep(totalSteps);
      setPendingComplete(true);
    }
  }, [
    tasks,
    currentStep,
    isCompleted,
    isEmbedding,
    totalSteps,
    rollbackMutation,
    onboardingMutation.isSuccess,
    onboardingTaskId,
  ]);

  const handleComplete = () => {
    const currentProvider = isEmbedding
      ? settings.embedding_provider
      : settings.llm_provider;

    if (
      !currentProvider ||
      (isEmbedding && !settings.embedding_model) ||
      (!isEmbedding && !settings.llm_model)
    ) {
      toast.error("Please complete all required fields");
      return;
    }

    // Clear any previous error
    setError(null);

    // Prepare onboarding data with provider-specific fields
    const onboardingData: OnboardingVariables = {};

    // Set the provider field
    if (isEmbedding) {
      onboardingData.embedding_provider = currentProvider;
      onboardingData.embedding_model = settings.embedding_model;
    } else {
      onboardingData.llm_provider = currentProvider;
      onboardingData.llm_model = settings.llm_model;
    }

    // Add provider-specific credentials based on the selected provider
    if (currentProvider === "openai" && settings.openai_api_key) {
      onboardingData.openai_api_key = settings.openai_api_key;
    } else if (currentProvider === "anthropic" && settings.anthropic_api_key) {
      onboardingData.anthropic_api_key = settings.anthropic_api_key;
    } else if (currentProvider === "watsonx") {
      if (settings.watsonx_api_key) {
        onboardingData.watsonx_api_key = settings.watsonx_api_key;
      }
      if (settings.watsonx_endpoint) {
        onboardingData.watsonx_endpoint = settings.watsonx_endpoint;
      }
      if (settings.watsonx_project_id) {
        onboardingData.watsonx_project_id = settings.watsonx_project_id;
      }
    } else if (currentProvider === "ollama" && settings.ollama_endpoint) {
      onboardingData.ollama_endpoint = settings.ollama_endpoint;
    }

    // Providers configured through the generic form submit their credentials
    // as-is; the backend stores whatever field keys the provider declares.
    const generic = settings.provider_credentials?.[currentProvider];
    if (generic && Object.keys(generic).length > 0) {
      onboardingData.provider_credentials = { [currentProvider]: generic };
    }

    trackButton({
      CTA: isEmbedding ? "Complete - Embedding Setup" : "Complete - LLM Setup",
      elementId: "onboarding-complete-button",
      namespace: "onboarding",
      payload: isEmbedding
        ? {
            embedding_provider: currentProvider,
            embedding_model: settings.embedding_model,
          }
        : { llm_provider: currentProvider, llm_model: settings.llm_model },
    });

    // Record the start time when user clicks Complete
    setProcessingStartTime(Date.now());
    onboardingMutation.mutate(onboardingData);
    setCurrentStep(0);
  };

  const isComplete =
    (isEmbedding && !!settings.embedding_model) ||
    (!isEmbedding && !!settings.llm_model && isDoclingHealthy);

  return (
    <AnimatePresence mode="wait">
      {currentStep === null ? (
        <motion.div
          key="onboarding-form"
          initial={{ opacity: 0, y: -24 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 24 }}
          transition={{ duration: 0.4, ease: "easeInOut" }}
        >
          <div className={`w-full max-w-[600px] flex flex-col`}>
            <AnimatePresence mode="wait">
              {error && (
                <motion.div
                  key="error"
                  initial={{ opacity: 1, y: 0, height: "auto" }}
                  exit={{ opacity: 0, y: -10, height: 0 }}
                >
                  <div className="pb-6 flex items-center gap-4">
                    <X className="w-4 h-4 text-destructive shrink-0" />
                    <span
                      data-testid="onboarding-error"
                      className="text-mmd text-muted-foreground"
                    >
                      {error}
                    </span>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
            <div className={`w-full flex flex-col gap-6`}>
              <Tabs
                value={modelProvider}
                onValueChange={handleSetModelProvider}
              >
                <TabsList className="mb-4">
                  {tabProviders.map((providerKey) => {
                    const chrome = getProviderChrome(
                      providerKey,
                      providerDisplayNames[providerKey],
                    );
                    const Logo = chrome.logo;
                    const selected = modelProvider === providerKey;
                    return (
                      <TabsTrigger
                        key={providerKey}
                        value={providerKey}
                        data-testid={`${providerKey}-${isEmbedding ? "embedding" : "llm"}-tab`}
                        className={cn(
                          error &&
                            selected &&
                            "data-[state=active]:border-destructive",
                        )}
                      >
                        <TabTrigger
                          selected={selected}
                          isLoading={isLoadingModels}
                        >
                          <div
                            className={cn(
                              "flex items-center justify-center gap-2 w-8 h-8 rounded-none border",
                              selected
                                ? (chrome.tabLogoBgColor ?? chrome.logoBgColor)
                                : "bg-muted",
                            )}
                          >
                            <Logo
                              className={cn(
                                "w-4 h-4 shrink-0",
                                selected
                                  ? (chrome.tabLogoColor ?? chrome.logoColor)
                                  : "text-muted-foreground",
                              )}
                            />
                          </div>
                          {chrome.name}
                        </TabTrigger>
                      </TabsTrigger>
                    );
                  })}
                </TabsList>
                {tabProviders.map((providerKey) => (
                  <TabsContent key={providerKey} value={providerKey}>
                    {providerKey === "anthropic" ? (
                      <AnthropicOnboarding
                        setSettings={setSettings}
                        isEmbedding={isEmbedding}
                        hasEnvApiKey={
                          currentSettings?.providers?.anthropic?.has_api_key ===
                          true
                        }
                      />
                    ) : providerKey === "openai" ? (
                      <OpenAIOnboarding
                        setSettings={setSettings}
                        isEmbedding={isEmbedding}
                        hasEnvApiKey={
                          currentSettings?.providers?.openai?.has_api_key ===
                          true
                        }
                        alreadyConfigured={
                          providerAlreadyConfigured &&
                          modelProvider === "openai"
                        }
                      />
                    ) : providerKey === "watsonx" ? (
                      <IBMOnboarding
                        setSettings={setSettings}
                        isEmbedding={isEmbedding}
                        alreadyConfigured={
                          providerAlreadyConfigured &&
                          modelProvider === "watsonx"
                        }
                        existingEndpoint={
                          currentSettings?.providers?.watsonx?.endpoint
                        }
                        existingProjectId={
                          currentSettings?.providers?.watsonx?.project_id
                        }
                        hasEnvApiKey={
                          currentSettings?.providers?.watsonx?.has_api_key ===
                          true
                        }
                      />
                    ) : providerKey === "ollama" ? (
                      <OllamaOnboarding
                        setSettings={setSettings}
                        isEmbedding={isEmbedding}
                        alreadyConfigured={
                          providerAlreadyConfigured &&
                          modelProvider === "ollama"
                        }
                        existingEndpoint={
                          currentSettings?.providers?.ollama?.endpoint
                        }
                      />
                    ) : (
                      <GenericOnboarding
                        provider={providerKey}
                        displayName={providerDisplayNames[providerKey]}
                        setSettings={setSettings}
                        isEmbedding={isEmbedding}
                        providers={currentSettings?.providers}
                      />
                    )}
                  </TabsContent>
                ))}
              </Tabs>

              <Tooltip>
                <TooltipTrigger asChild>
                  <div>
                    <Button
                      size="sm"
                      data-testid="onboarding-complete-button"
                      onClick={handleComplete}
                      disabled={!isComplete || isLoadingModels}
                      loading={onboardingMutation.isPending}
                    >
                      <span className="select-none">Complete</span>
                    </Button>
                  </div>
                </TooltipTrigger>
                {!isComplete && (
                  <TooltipContent>
                    {isLoadingModels
                      ? "Loading models..."
                      : settings.llm_model &&
                          settings.embedding_model &&
                          !isDoclingHealthy
                        ? "docling-serve must be running to continue"
                        : "Please fill in all required fields"}
                  </TooltipContent>
                )}
              </Tooltip>
            </div>
          </div>
        </motion.div>
      ) : (
        <motion.div
          key="provider-steps"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 24 }}
          transition={{ duration: 0.4, ease: "easeInOut" }}
        >
          <AnimatedProviderSteps
            currentStep={currentStep}
            isCompleted={isCompleted}
            setCurrentStep={setCurrentStep}
            steps={isEmbedding ? EMBEDDING_STEP_LIST : STEP_LIST}
            processingStartTime={processingStartTime}
            hasError={!!error}
          />
        </motion.div>
      )}
    </AnimatePresence>
  );
};

export default OnboardingCard;
