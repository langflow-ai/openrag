import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { FormProvider, useForm } from "react-hook-form";
import { toast } from "sonner";
import { useUpdateSettingsMutation } from "@/app/api/mutations/useUpdateSettingsMutation";
import { useGetOllamaModelsQuery } from "@/app/api/queries/useGetModelsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import type { ProviderHealthResponse } from "@/app/api/queries/useProviderHealthQuery";
import OllamaLogo from "@/components/icons/ollama-logo";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuth } from "@/contexts/auth-context";
import ModelProviderDialogFooter from "./model-provider-dialog-footer";
import {
  OllamaSettingsForm,
  type OllamaSettingsFormData,
} from "./ollama-settings-form";

const OllamaSettingsDialog = ({
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
  const router = useRouter();

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const isOllamaConfigured = settings.providers?.ollama?.configured === true;

  const otherProviderConfigured =
    settings.providers?.openai?.configured === true ||
    settings.providers?.anthropic?.configured === true ||
    settings.providers?.watsonx?.configured === true;

  const canRemoveOllama = isOllamaConfigured && otherProviderConfigured;

  const methods = useForm<OllamaSettingsFormData>({
    mode: "onSubmit",
    defaultValues: {
      endpoint: isOllamaConfigured
        ? settings.providers?.ollama?.endpoint
        : "http://localhost:11434",
    },
  });

  useEffect(() => {
    // Reset form state on dialog open
    if (open) methods.reset();
  }, [open]);

  const { handleSubmit, watch } = methods;
  const endpoint = watch("endpoint");

  const { refetch: validateCredentials } = useGetOllamaModelsQuery(
    {
      endpoint: endpoint,
    },
    {
      enabled: false,
    },
  );

  const settingsMutation = useUpdateSettingsMutation({
    onSuccess: () => {
      // Update provider health cache to healthy since backend validated the setup
      const healthData: ProviderHealthResponse = {
        status: "healthy",
        message: "Provider is configured and working correctly",
        provider: "ollama",
      };
      queryClient.setQueryData(["provider", "health"], healthData);

      toast.message("Ollama successfully configured", {
        description:
          "You can now access the provided language and embedding models.",
        duration: Infinity,
        closeButton: true,
        icon: <OllamaLogo className="w-4 h-4" />,
        action: {
          label: "Settings",
          onClick: () => {
            router.push("/settings?focusLlmModel=true");
          },
        },
      });
      setOpen(false);
    },
  });

  const removeMutation = useUpdateSettingsMutation({
    onSuccess: () => {
      toast.success("Ollama configuration removed");
      setShowRemoveConfirm(false);
      setOpen(false);
    },
  });

  const onSubmit = async (data: OllamaSettingsFormData) => {
    // Clear any previous validation errors
    setValidationError(null);

    // Validate endpoint by fetching models
    setIsValidating(true);
    const result = await validateCredentials();
    setIsValidating(false);

    if (result.isError) {
      setValidationError(result.error);
      return;
    }

    settingsMutation.mutate({
      ollama_endpoint: data.endpoint,
    });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setShowRemoveConfirm(false);
        setOpen(o);
      }}
    >
      <DialogContent className="max-w-2xl">
        <FormProvider {...methods}>
          <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4">
            <DialogHeader className="mb-2">
              <DialogTitle className="flex items-center gap-3">
                <div className="w-8 h-8 rounded flex items-center justify-center bg-white border">
                  <OllamaLogo className="text-black" />
                </div>
                Ollama Setup
              </DialogTitle>
            </DialogHeader>

            <OllamaSettingsForm
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
              {removeMutation.isError && (
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
              onCancelRemove={() => setShowRemoveConfirm(false)}
              onConfirmRemove={() =>
                removeMutation.mutate({ remove_ollama_config: true })
              }
              isRemovePending={removeMutation.isPending}
              isConfigured={isOllamaConfigured}
              canRemove={canRemoveOllama}
              removeDisabledTooltip="Configure another model provider before removing Ollama"
              onRequestRemove={() => setShowRemoveConfirm(true)}
              onCancel={() => setOpen(false)}
              isSavePending={settingsMutation.isPending}
              isValidating={isValidating}
            />
          </form>
        </FormProvider>
      </DialogContent>
    </Dialog>
  );
};

export default OllamaSettingsDialog;
