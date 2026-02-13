"use client";

import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  type OnboardingVariables,
  useOnboardingMutation,
} from "@/app/api/mutations/useOnboardingMutation";
import { useOnboardingRollbackMutation } from "@/app/api/mutations/useOnboardingRollbackMutation";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { useGetTasksQuery } from "@/app/api/queries/useGetTasksQuery";
import type { ProviderHealthResponse } from "@/app/api/queries/useProviderHealthQuery";
import { useDoclingHealth } from "@/components/docling-health-banner";
import AnthropicLogo from "@/components/icons/anthropic-logo";
import IBMLogo from "@/components/icons/ibm-logo";
import OllamaLogo from "@/components/icons/ollama-logo";
import OpenAILogo from "@/components/icons/openai-logo";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { AnimatedProviderSteps } from "./animated-provider-steps";
import { AnthropicOnboarding } from "./anthropic-onboarding";
import { IBMOnboarding } from "./ibm-onboarding";
import { OllamaOnboarding } from "./ollama-onboarding";
import { OpenAIOnboarding } from "./openai-onboarding";
import { TabTrigger } from "./tab-trigger";

interface OnboardingCardProps {
  onComplete: () => void;
  isCompleted?: boolean;
  isEmbedding?: boolean;
  setIsLoadingModels?: (isLoading: boolean) => void;
  setLoadingStatus?: (status: string[]) => void;
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

  const [modelProvider, setModelProvider] = useState<string>(
    isEmbedding ? "openai" : "anthropic",
  );

  const [isLoadingModels, setIsLoadingModels] = useState<boolean>(false);

  const queryClient = useQueryClient();

  // Fetch current settings to check if providers are already configured
  const { data: currentSettings } = useGetSettingsQuery();

  // Auto-select the first provider that has an API key set in env vars
  useEffect(() => {
    if (!currentSettings?.providers) return;

    // Define provider order based on whether it's embedding or not
    const providerOrder = isEmbedding
      ? ["openai", "watsonx", "ollama"]
      : ["anthropic", "openai", "watsonx", "ollama"];

    // Find the first provider with an API key
    for (const provider of providerOrder) {
      if (
        provider === "anthropic" &&
        currentSettings.providers.anthropic?.has_api_key
      ) {
        setModelProvider("anthropic");
        return;
      } else if (provider === "openai" && currentSettings.providers.openai?.has_api_key) {
        setModelProvider("openai");
        return;
      } else if (
        provider === "watsonx" &&
        currentSettings.providers.watsonx?.has_api_key
      ) {
        setModelProvider("watsonx");
        return;
      } else if (
        provider === "ollama" &&
        currentSettings.providers.ollama?.endpoint
      ) {
        setModelProvider("ollama");
        return;
      }
    }
  }, [currentSettings, isEmbedding]);

  const handleSetModelProvider = (provider: string) => {
    setIsLoadingModels(false);
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
    return false;
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

  // Track which tasks we've already handled to prevent infinite loops
  const handledFailedTasksRef = useRef<Set<string>>(new Set());

  // Query tasks to track completion
  const { data: tasks } = useGetTasksQuery({
    enabled: currentStep !== null && !isCompleted, // Only poll when onboarding has started and stop once step is complete
    refetchInterval: currentStep !== null ? 1000 : false, // Poll every 1 second during onboarding
  });

  // Rollback mutation
  const rollbackMutation = useOnboardingRollbackMutation({
    onSuccess: () => {
      console.log("Onboarding rolled back successfully");
      // Reset to provider selection step
      // Error message is already set before calling mutate
      setCurrentStep(null);
    },
    onError: (error) => {
      console.error("Failed to rollback onboarding", error);
      // Preserve existing error message if set, otherwise show rollback error
      setError((prevError) => prevError || `Failed to rollback: ${error.message}`);
      // Still reset to provider selection even if rollback fails
      setCurrentStep(null);
    },
  });

  // Monitor tasks and call onComplete when all tasks are done
  useEffect(() => {
    if (currentStep === null || !tasks || !isEmbedding) {
      return;
    }

    // Check if there are any active tasks (pending, running, or processing)
    const activeTasks = tasks.find(
      (task) =>
        task.status === "pending" ||
        task.status === "running" ||
        task.status === "processing",
    );

    // Check if any task failed at the top level
    const failedTask = tasks.find(
      (task) => task.status === "failed" || task.status === "error",
    );

    // Check if any completed task has at least one failed file
    const completedTaskWithFailedFile = tasks.find((task) => {
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
      console.error(
        "Task failed, jumping back one step",
        taskWithFailure,
      );

      // Mark this task as handled to prevent infinite loops
      handledFailedTasksRef.current.add(taskWithFailure.task_id);

      // Extract error messages from failed files
      const errorMessages: string[] = [];
      if (taskWithFailure.files) {
        Object.values(taskWithFailure.files).forEach((file) => {
          if (
            (file.status === "failed" || file.status === "error") &&
            file.error
          ) {
            errorMessages.push(file.error);
          }
        });
      }

      // Also check task-level error
      if (taskWithFailure.error) {
        errorMessages.push(taskWithFailure.error);
      }

      // Use the first error message, or a generic message if no errors found
      const errorMessage =
        errorMessages.length > 0
          ? errorMessages[0]
          : "Sample data ingestion failed. Please try again.";

      // Set error message and jump back one step (exactly like onboardingMutation.onError)
      setError(errorMessage);
      setCurrentStep(totalSteps);
      rollbackMutation.mutate();
      return;
    }

    // If at least one processed file, no failures, and we've started onboarding, complete it
    if (
      (((!activeTasks || (activeTasks.successful_files ?? 0) > 0) &&
        tasks.length > 0) ||
        (tasks.length === 0 && currentStep === totalSteps - 1)) && // Complete because no files were ingested
      !isCompleted &&
      !taskWithFailure

    ) {
      // Set to final step to show "Done"
      setCurrentStep(totalSteps);
      // Wait a bit before completing
      setTimeout(() => {
        onComplete();
      }, 1000);
    }
  }, [tasks, currentStep, onComplete, isCompleted, isEmbedding, totalSteps, rollbackMutation]);

  // Mutations
  const onboardingMutation = useOnboardingMutation({
    onSuccess: (data) => {
      console.log("Onboarding completed successfully", data);

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
        setCurrentStep(totalSteps);
        setTimeout(() => {
          onComplete();
        }, 1000);
      } else {
        setCurrentStep(0);
      }
    },
    onError: (error) => {
      setError(error.message);
      setCurrentStep(totalSteps);
      rollbackMutation.mutate();
    },
  });

  const handleComplete = () => {
    const currentProvider = isEmbedding
      ? settings.embedding_provider
      : settings.llm_provider;

    if (
      !currentProvider ||
      (isEmbedding &&
        !settings.embedding_model &&
        !showProviderConfiguredMessage) ||
      (!isEmbedding && !settings.llm_model)
    ) {
      toast.error("Please complete all required fields");
      return;
    }

    // Clear any previous error
    setError(null);

    // Prepare onboarding data with provider-specific fields
    const onboardingData: OnboardingVariables = {
    };

    // Set the provider field
    if (isEmbedding) {
      onboardingData.embedding_provider = currentProvider;
      // If provider is already configured, use the existing embedding model from settings
      // Otherwise, use the embedding model from the form
      if (
        showProviderConfiguredMessage &&
        currentSettings?.knowledge?.embedding_model
      ) {
        onboardingData.embedding_model =
          currentSettings.knowledge.embedding_model;
      } else {
        onboardingData.embedding_model = settings.embedding_model;
      }
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

    // Record the start time when user clicks Complete
    setProcessingStartTime(Date.now());
    onboardingMutation.mutate(onboardingData);
    setCurrentStep(0);
  };

  const isComplete =
    (isEmbedding &&
      (!!settings.embedding_model || showProviderConfiguredMessage)) ||
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
                    <span className="text-mmd text-muted-foreground">
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
                  {!isEmbedding && (
                    <TabsTrigger
                      value="anthropic"
                      className={cn(
                        error &&
                        modelProvider === "anthropic" &&
                        "data-[state=active]:border-destructive",
                      )}
                    >
                      <TabTrigger
                        selected={modelProvider === "anthropic"}
                        isLoading={isLoadingModels}
                      >
                        <div
                          className={cn(
                            "flex items-center justify-center gap-2 w-8 h-8 rounded-md border",
                            modelProvider === "anthropic"
                              ? "bg-[#D97757]"
                              : "bg-muted",
                          )}
                        >
                          <AnthropicLogo
                            className={cn(
                              "w-4 h-4 shrink-0",
                              modelProvider === "anthropic"
                                ? "text-black"
                                : "text-muted-foreground",
                            )}
                          />
                        </div>
                        Anthropic
                      </TabTrigger>
                    </TabsTrigger>
                  )}
                  <TabsTrigger
                    value="openai"
                    className={cn(
                      error &&
                      modelProvider === "openai" &&
                      "data-[state=active]:border-destructive",
                    )}
                  >
                    <TabTrigger
                      selected={modelProvider === "openai"}
                      isLoading={isLoadingModels}
                    >
                      <div
                        className={cn(
                          "flex items-center justify-center gap-2 w-8 h-8 rounded-md border",
                          modelProvider === "openai" ? "bg-white" : "bg-muted",
                        )}
                      >
                        <OpenAILogo
                          className={cn(
                            "w-4 h-4 shrink-0",
                            modelProvider === "openai"
                              ? "text-black"
                              : "text-muted-foreground",
                          )}
                        />
                      </div>
                      OpenAI
                    </TabTrigger>
                  </TabsTrigger>
                  <TabsTrigger
                    value="watsonx"
                    className={cn(
                      error &&
                      modelProvider === "watsonx" &&
                      "data-[state=active]:border-destructive",
                    )}
                  >
                    <TabTrigger
                      selected={modelProvider === "watsonx"}
                      isLoading={isLoadingModels}
                    >
                      <div
                        className={cn(
                          "flex items-center justify-center gap-2 w-8 h-8 rounded-md border",
                          modelProvider === "watsonx"
                            ? "bg-[#1063FE]"
                            : "bg-muted",
                        )}
                      >
                        <IBMLogo
                          className={cn(
                            "w-4 h-4 shrink-0",
                            modelProvider === "watsonx"
                              ? "text-white"
                              : "text-muted-foreground",
                          )}
                        />
                      </div>
                      IBM watsonx.ai
                    </TabTrigger>
                  </TabsTrigger>
                  <TabsTrigger
                    value="ollama"
                    className={cn(
                      error &&
                      modelProvider === "ollama" &&
                      "data-[state=active]:border-destructive",
                    )}
                  >
                    <TabTrigger
                      selected={modelProvider === "ollama"}
                      isLoading={isLoadingModels}
                    >
                      <div
                        className={cn(
                          "flex items-center justify-center gap-2 w-8 h-8 rounded-md border",
                          modelProvider === "ollama" ? "bg-white" : "bg-muted",
                        )}
                      >
                        <OllamaLogo
                          className={cn(
                            "w-4 h-4 shrink-0",
                            modelProvider === "ollama"
                              ? "text-black"
                              : "text-muted-foreground",
                          )}
                        />
                      </div>
                      Ollama
                    </TabTrigger>
                  </TabsTrigger>
                </TabsList>
                {!isEmbedding && (
                  <TabsContent value="anthropic">
                    <AnthropicOnboarding
                      setSettings={setSettings}
                      setIsLoadingModels={setIsLoadingModels}
                      isEmbedding={isEmbedding}
                      hasEnvApiKey={
                        currentSettings?.providers?.anthropic?.has_api_key ===
                        true
                      }
                    />
                  </TabsContent>
                )}
                <TabsContent value="openai">
                  <OpenAIOnboarding
                    setSettings={setSettings}
                    setIsLoadingModels={setIsLoadingModels}
                    isEmbedding={isEmbedding}
                    hasEnvApiKey={
                      currentSettings?.providers?.openai?.has_api_key === true
                    }
                    alreadyConfigured={providerAlreadyConfigured && modelProvider === "openai"}
                  />
                </TabsContent>
                <TabsContent value="watsonx">
                  <IBMOnboarding
                    setSettings={setSettings}
                    setIsLoadingModels={setIsLoadingModels}
                    isEmbedding={isEmbedding}
                    alreadyConfigured={providerAlreadyConfigured && modelProvider === "watsonx"}
                    existingEndpoint={currentSettings?.providers?.watsonx?.endpoint}
                    existingProjectId={currentSettings?.providers?.watsonx?.project_id}
                    hasEnvApiKey={currentSettings?.providers?.watsonx?.has_api_key === true}
                  />
                </TabsContent>
                <TabsContent value="ollama">
                  <OllamaOnboarding
                    setSettings={setSettings}
                    setIsLoadingModels={setIsLoadingModels}
                    isEmbedding={isEmbedding}
                    alreadyConfigured={providerAlreadyConfigured && modelProvider === "ollama"}
                    existingEndpoint={currentSettings?.providers?.ollama?.endpoint}
                  />
                </TabsContent>
              </Tabs>

              <Tooltip>
                <TooltipTrigger asChild>
                  <div>
                    <Button
                      size="sm"
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
                      : !!settings.llm_model &&
                        !!settings.embedding_model &&
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
