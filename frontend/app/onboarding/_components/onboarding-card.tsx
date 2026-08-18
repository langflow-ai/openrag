"use client";

import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import {
  type OnboardingVariables,
  useOnboardingMutation,
} from "@/app/api/mutations/useOnboardingMutation";
import { useOnboardingRollbackMutation } from "@/app/api/mutations/useOnboardingRollbackMutation";
import { useGetModelCatalogQuery } from "@/app/api/queries/useGetModelsQuery";
import {
  type ProviderSettings,
  useGetSettingsQuery,
} from "@/app/api/queries/useGetSettingsQuery";
import { useGetTasksQuery } from "@/app/api/queries/useGetTasksQuery";
import type { ProviderHealthResponse } from "@/app/api/queries/useProviderHealthQuery";
import {
  findGroupedSelection,
  groupedCatalogOptions,
  onboardingCatalogConfigured,
  providerCredentialsSatisfied,
  savedCredentialValuesForProvider,
  savedSecretFieldsForProvider,
} from "@/app/settings/_helpers/catalog-models";
import {
  CLOUD_EXCLUDED_PROVIDERS,
  EMBEDDING_PROVIDER_ORDER,
  getModelLogo,
  LLM_PROVIDER_ORDER,
} from "@/app/settings/_helpers/model-helpers";
import { useDoclingHealth } from "@/components/docling-health-banner";
import { LabelWrapper } from "@/components/label-wrapper";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useIsCloudBrand } from "@/contexts/brand-context";
import {
  trackButton,
  trackProcessFailure,
  trackProcessSuccess,
} from "@/lib/analytics";
import { formatProviderErrorMessage } from "@/lib/chat-stream-errors";
import { AnimatedProviderSteps } from "./animated-provider-steps";
import { ModelFeatures } from "./model-features";
import { ModelSelector } from "./model-selector";
import {
  type CredentialStatus,
  OnboardingCredentialFields,
} from "./onboarding-credential-fields";

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
  const isCloudBrand = useIsCloudBrand();

  const [modelProvider, setModelProvider] = useState<string>("");
  const [credentialsReady, setCredentialsReady] = useState(false);
  const autoSelectedRef = useRef(false);

  const isLoadingModels = useIsFetching({ queryKey: ["models"] }) > 0;

  const queryClient = useQueryClient();

  const { data: currentSettings } = useGetSettingsQuery();
  const {
    data: catalog,
    isLoading: catalogLoading,
    error: catalogError,
  } = useGetModelCatalogQuery();

  const groupedModels = useMemo(() => {
    const groups = groupedCatalogOptions(
      catalog,
      onboardingCatalogConfigured(isEmbedding, isCloudBrand),
      isEmbedding ? "embedding" : "language",
    );
    return groups.map((group) => ({
      group: group.group,
      provider: group.key,
      icon: getModelLogo("", group.key),
      options: group.options,
    }));
  }, [catalog, isCloudBrand, isEmbedding]);

  const totalSteps = isEmbedding
    ? EMBEDDING_STEP_LIST.length
    : STEP_LIST.length;

  const [settings, setSettings] = useState<OnboardingVariables>({
    [isEmbedding ? "embedding_provider" : "llm_provider"]: "",
    embedding_model: "",
    llm_model: "",
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

  const [prevProviders, setPrevProviders] = useState<
    ProviderSettings | undefined | null
  >(null);
  if (currentSettings?.providers !== prevProviders) {
    setPrevProviders(currentSettings?.providers);
    autoSelectedRef.current = false;
  }

  const handleModelChange = useCallback(
    (value: string, provider?: string) => {
      setModelProvider((prevProvider) => {
        const nextProvider = provider || prevProvider;
        if (nextProvider !== prevProvider) {
          setCredentialsReady(false);
        }
        return nextProvider;
      });
      setSettings((prev) => {
        const nextProvider =
          provider ||
          (isEmbedding ? prev.embedding_provider : prev.llm_provider) ||
          "";
        return {
          ...prev,
          ...(isEmbedding
            ? { embedding_provider: nextProvider, embedding_model: value }
            : { llm_provider: nextProvider, llm_model: value }),
        };
      });
      setError(null);
    },
    [isEmbedding],
  );

  useEffect(() => {
    if (autoSelectedRef.current) {
      return;
    }
    if (
      !currentSettings?.providers ||
      catalogLoading ||
      groupedModels.length === 0
    ) {
      return;
    }
    const fullOrder = isEmbedding
      ? EMBEDDING_PROVIDER_ORDER
      : LLM_PROVIDER_ORDER;
    const providerOrder = isCloudBrand
      ? fullOrder.filter((p) => !CLOUD_EXCLUDED_PROVIDERS.includes(p))
      : fullOrder;

    const configuredProvider = (provider: string) =>
      providerCredentialsSatisfied(
        currentSettings.providers,
        provider,
        catalog,
      );

    if (isEmbedding) {
      const llmProvider = currentSettings.agent?.llm_provider;
      if (llmProvider && configuredProvider(llmProvider)) {
        const group = groupedModels.find(
          (entry) => entry.provider === llmProvider,
        );
        const first = group?.options[0];
        if (first) {
          autoSelectedRef.current = true;
          handleModelChange(first.value, first.provider ?? llmProvider);
          return;
        }
      }
    }

    for (const provider of providerOrder) {
      const hasSaved =
        configuredProvider(provider) ||
        (provider === "anthropic" &&
          currentSettings.providers.anthropic?.has_api_key) ||
        (provider === "openai" &&
          currentSettings.providers.openai?.has_api_key) ||
        (provider === "watsonx" &&
          currentSettings.providers.watsonx?.has_api_key) ||
        (provider === "ollama" && currentSettings.providers.ollama?.endpoint);
      if (!hasSaved) {
        continue;
      }
      const group = groupedModels.find((entry) => entry.provider === provider);
      const first = group?.options[0];
      if (first) {
        autoSelectedRef.current = true;
        handleModelChange(first.value, first.provider ?? provider);
        return;
      }
    }
    const openaiGroup = groupedModels.find(
      (entry) => entry.provider === "openai",
    );
    const openaiDefault =
      openaiGroup?.options.find((option) => option.default) ??
      openaiGroup?.options[0];
    if (openaiDefault) {
      autoSelectedRef.current = true;
      handleModelChange(openaiDefault.value, "openai");
      return;
    }
    autoSelectedRef.current = true;
  }, [
    catalog,
    catalogLoading,
    currentSettings?.agent?.llm_provider,
    currentSettings?.providers,
    groupedModels,
    handleModelChange,
    isCloudBrand,
    isEmbedding,
  ]);

  const [onboardingTaskId, setOnboardingTaskId] = useState<string | null>(null);

  const handledFailedTasksRef = useRef<Set<string>>(new Set());

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

  const { data: tasks } = useGetTasksQuery({
    enabled: currentStep !== null && !isCompleted,
    refetchInterval: currentStep !== null ? 1000 : false,
  });

  const rollbackMutation = useOnboardingRollbackMutation({
    onSuccess: () => {
      setCurrentStep(null);
    },
    onError: (error) => {
      console.error("Failed to rollback onboarding", error);
      setError(
        (prevError) => prevError || `Failed to rollback: ${error.message}`,
      );
      setCurrentStep(null);
    },
  });

  const onboardingMutation = useOnboardingMutation({
    onSuccess: (data) => {
      if (data.task_id) {
        setOnboardingTaskId(data.task_id);
      }

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

    const activeTasks = relevantTasks.find(
      (task) =>
        task.status === "pending" ||
        task.status === "running" ||
        task.status === "processing",
    );

    const failedTask = relevantTasks.find(
      (task) => task.status === "failed" || task.status === "error",
    );

    const completedTaskWithFailedFile = relevantTasks.find((task) => {
      if (!task.files || typeof task.files !== "object") {
        return false;
      }

      const fileEntries = Object.values(task.files);

      if (fileEntries.length === 0) {
        return false;
      }

      const hasFailedFile = fileEntries.some(
        (file) => file.status === "failed" || file.status === "error",
      );

      return hasFailedFile;
    });

    const taskWithFailure = failedTask || completedTaskWithFailedFile;

    if (
      taskWithFailure &&
      !rollbackMutation.isPending &&
      !isCompleted &&
      !handledFailedTasksRef.current.has(taskWithFailure.task_id)
    ) {
      console.error("Task failed, jumping back one step", taskWithFailure);

      handledFailedTasksRef.current.add(taskWithFailure.task_id);

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

  const savedSecretFields = savedSecretFieldsForProvider(
    currentSettings?.providers,
    modelProvider,
  );
  const savedCredentialValues = savedCredentialValuesForProvider(
    currentSettings?.providers,
    modelProvider,
  );
  const alreadyConfigured = providerCredentialsSatisfied(
    currentSettings?.providers,
    modelProvider,
    catalog,
  );

  useEffect(() => {
    if (modelProvider && alreadyConfigured) {
      setCredentialsReady(true);
    }
  }, [alreadyConfigured, modelProvider]);

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

    setError(null);

    const onboardingData: OnboardingVariables = {};

    if (isEmbedding) {
      onboardingData.embedding_provider = currentProvider;
      onboardingData.embedding_model = settings.embedding_model;
    } else {
      onboardingData.llm_provider = currentProvider;
      onboardingData.llm_model = settings.llm_model;
    }
    if (settings.provider_credentials && !alreadyConfigured) {
      onboardingData.provider_credentials = settings.provider_credentials;
    }

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

    setProcessingStartTime(Date.now());
    onboardingMutation.mutate(onboardingData);
    setCurrentStep(0);
  };

  const selectedModel = isEmbedding
    ? settings.embedding_model || ""
    : settings.llm_model || "";
  const selected = findGroupedSelection(
    groupedModels,
    selectedModel,
    modelProvider,
  );
  const selectedGroup = selected?.group;
  const selectedCatalogModel = selected?.option?.model;

  const isComplete =
    !!selectedModel && credentialsReady && (isEmbedding || isDoclingHealthy);

  const handleStatusChange = useCallback((status: CredentialStatus) => {
    setCredentialsReady(status.ready);
  }, []);

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
              <LabelWrapper
                label={isEmbedding ? "Embedding model" : "Language model"}
                helperText={
                  isEmbedding
                    ? "Model used for knowledge ingest and retrieval"
                    : "Model used for chat"
                }
                id={isEmbedding ? "embedding-model" : "language-model"}
                required
              >
                <ModelSelector
                  groupedOptions={groupedModels}
                  custom
                  data-testid={
                    isEmbedding
                      ? "embedding-model-selector"
                      : "language-model-selector"
                  }
                  value={selectedModel}
                  selectedProvider={modelProvider}
                  onValueChange={handleModelChange}
                  disabled={catalogLoading}
                  hasError={!!error}
                  placeholder={
                    catalogLoading ? "Loading models..." : "Select model..."
                  }
                  noOptionsPlaceholder={
                    catalogLoading ? "Loading models..." : "No models available"
                  }
                />
              </LabelWrapper>

              {selectedModel && selectedGroup && (
                <ModelFeatures
                  model={selectedCatalogModel ?? { model: selectedModel }}
                  providerName={selectedGroup.group}
                  provider={selectedGroup.provider}
                />
              )}

              {catalogError && (
                <p className="text-mmd text-destructive">
                  {catalogError.message}
                </p>
              )}

              {modelProvider && alreadyConfigured && (
                <p className="text-mmd text-muted-foreground">
                  Using the saved {selectedGroup?.group ?? modelProvider}{" "}
                  credentials.
                </p>
              )}

              {modelProvider && !alreadyConfigured && (
                <OnboardingCredentialFields
                  key={modelProvider}
                  provider={modelProvider}
                  catalog={catalog}
                  savedValues={savedCredentialValues}
                  savedSecretFields={savedSecretFields}
                  setSettings={setSettings}
                  onStatusChange={handleStatusChange}
                />
              )}

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
                    {catalogLoading || isLoadingModels
                      ? "Loading models..."
                      : selectedModel && !isEmbedding && !isDoclingHealthy
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
