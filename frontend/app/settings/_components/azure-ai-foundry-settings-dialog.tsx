"use client";

import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { FormProvider, useForm } from "react-hook-form";
import { toast } from "sonner";
import {
  type AffectedEmbeddingModel,
  isEmbeddingProviderInUseError,
  useUpdateSettingsMutation,
} from "@/app/api/mutations/useUpdateSettingsMutation";
import { useGetAzureAIFoundryModelsQuery } from "@/app/api/queries/useGetModelsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import type { ProviderHealthResponse } from "@/app/api/queries/useProviderHealthQuery";
import AzureAIFoundryLogo from "@/components/icons/azure-ai-foundry-logo";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuth } from "@/contexts/auth-context";
import {
  AzureAIFoundrySettingsForm,
  type AzureAIFoundrySettingsFormData,
} from "./azure-ai-foundry-settings-form";
import ModelProviderDialogFooter from "./model-provider-dialog-footer";

const AzureAIFoundrySettingsDialog = ({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
}) => {
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const queryClient = useQueryClient();
  const [isValidating, setIsValidating] = useState(false);
  const [validationError, setValidationError] = useState<Error | null>(null);
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false);
  const [affectedModels, setAffectedModels] = useState<
    AffectedEmbeddingModel[] | undefined
  >(undefined);
  const router = useRouter();

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const isAzureConfigured =
    settings.providers?.azure_ai_foundry?.configured === true;

  const canRemoveAzure =
    isAzureConfigured &&
    (settings.providers?.openai?.configured === true ||
      settings.providers?.anthropic?.configured === true ||
      settings.providers?.watsonx?.configured === true ||
      settings.providers?.ollama?.configured === true);

  const methods = useForm<AzureAIFoundrySettingsFormData>({
    mode: "onSubmit",
    defaultValues: {
      endpoint: settings.providers?.azure_ai_foundry?.endpoint ?? "",
      apiKey: "",
      llmDeploymentName:
        settings.agent?.llm_provider === "azure_ai_foundry"
          ? (settings.agent?.llm_model ?? "")
          : "",
      embeddingDeploymentName:
        settings.knowledge?.embedding_provider === "azure_ai_foundry"
          ? (settings.knowledge?.embedding_model ?? "")
          : "",
    },
  });

  useEffect(() => {
    if (open) methods.reset();
  }, [open]);

  const { handleSubmit, watch } = methods;
  const endpoint = watch("endpoint");
  const apiKey = watch("apiKey");
  const llmDeploymentName = watch("llmDeploymentName");
  const embeddingDeploymentName = watch("embeddingDeploymentName");

  const { refetch: validateCredentials } = useGetAzureAIFoundryModelsQuery(
    { endpoint, apiKey },
    { enabled: false },
  );

  const settingsMutation = useUpdateSettingsMutation({
    onSuccess: () => {
      const healthData: ProviderHealthResponse = {
        status: "healthy",
        message: "Provider is configured and working correctly",
        provider: "azure_ai_foundry",
      };
      queryClient.setQueryData(["provider", "health"], healthData);

      toast.message("Azure AI Foundry successfully configured", {
        description:
          "Configure your deployment names in Settings to start using language and embedding models.",
        duration: Infinity,
        closeButton: true,
        icon: <AzureAIFoundryLogo className="w-4 h-4" />,
        action: {
          label: "Settings",
          onClick: () => {
            router.push("/settings/langflow?focusLlmModel=true");
          },
        },
      });
      setOpen(false);
    },
  });

  const removeMutation = useUpdateSettingsMutation({
    onSuccess: () => {
      toast.success("Azure AI Foundry configuration removed");
      setShowRemoveConfirm(false);
      setAffectedModels(undefined);
      setOpen(false);
    },
    onError: (err) => {
      if (isEmbeddingProviderInUseError(err)) {
        setAffectedModels(err.affectedModels);
      }
    },
  });

  const onSubmit = async (data: AzureAIFoundrySettingsFormData) => {
    setValidationError(null);
    setIsValidating(true);
    const result = await validateCredentials();
    setIsValidating(false);

    if (result.isError) {
      setValidationError(result.error);
      return;
    }

    const payload: {
      azure_ai_foundry_endpoint: string;
      azure_ai_foundry_api_key?: string;
      llm_model?: string;
      llm_provider?: string;
      embedding_model?: string;
      embedding_provider?: string;
    } = {
      azure_ai_foundry_endpoint: data.endpoint,
    };

    if (data.apiKey) {
      payload.azure_ai_foundry_api_key = data.apiKey;
    }
    if (data.llmDeploymentName) {
      payload.llm_model = data.llmDeploymentName;
      payload.llm_provider = "azure_ai_foundry";
    }
    if (data.embeddingDeploymentName) {
      payload.embedding_model = data.embeddingDeploymentName;
      payload.embedding_provider = "azure_ai_foundry";
    }

    settingsMutation.mutate(payload);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setShowRemoveConfirm(false);
        setAffectedModels(undefined);
        setOpen(o);
      }}
    >
      <DialogContent autoFocus={false} className="max-w-2xl">
        <FormProvider {...methods}>
          <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4">
            <DialogHeader className="mb-2">
              <DialogTitle className="flex items-center gap-3">
                <div className="w-8 h-8 rounded flex items-center justify-center bg-[#0078D4]">
                  <AzureAIFoundryLogo className="text-white" />
                </div>
                Azure AI Foundry Setup
              </DialogTitle>
            </DialogHeader>

            <AzureAIFoundrySettingsForm
              modelsError={validationError}
              isLoadingModels={isValidating}
            />

            <AnimatePresence mode="wait">
              {settingsMutation.isError && (
                <motion.div
                  key="error"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                >
                  <p className="rounded-lg border border-destructive p-4">
                    {settingsMutation.error?.message}
                  </p>
                </motion.div>
              )}
              {removeMutation.isError &&
                !isEmbeddingProviderInUseError(removeMutation.error) && (
                  <motion.div
                    key="remove-error"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -10 }}
                  >
                    <p className="rounded-lg border border-destructive p-4">
                      {removeMutation.error?.message}
                    </p>
                  </motion.div>
                )}
            </AnimatePresence>

            <ModelProviderDialogFooter
              showRemoveConfirm={showRemoveConfirm}
              onCancelRemove={() => {
                setShowRemoveConfirm(false);
                setAffectedModels(undefined);
              }}
              onConfirmRemove={() =>
                removeMutation.mutate({
                  remove_azure_ai_foundry_config: true,
                  force_remove: !!affectedModels,
                })
              }
              isRemovePending={removeMutation.isPending}
              isConfigured={isAzureConfigured}
              canRemove={canRemoveAzure}
              providerKey="azure_ai_foundry"
              removeDisabledTooltip="Configure another model provider before removing Azure AI Foundry"
              onRequestRemove={() => setShowRemoveConfirm(true)}
              onCancel={() => setOpen(false)}
              isSavePending={settingsMutation.isPending}
              isValidating={isValidating}
              affectedModels={affectedModels}
            />
          </form>
        </FormProvider>
      </DialogContent>
    </Dialog>
  );
};

export default AzureAIFoundrySettingsDialog;
