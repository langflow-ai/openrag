import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { FormProvider, useForm } from "react-hook-form";
import { toast } from "sonner";
import { useUpdateSettingsMutation } from "@/app/api/mutations/useUpdateSettingsMutation";
import { useGetAnthropicModelsQuery } from "@/app/api/queries/useGetModelsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import type { ProviderHealthResponse } from "@/app/api/queries/useProviderHealthQuery";
import AnthropicLogo from "@/components/icons/anthropic-logo";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuth } from "@/contexts/auth-context";
import {
  AnthropicSettingsForm,
  type AnthropicSettingsFormData,
} from "./anthropic-settings-form";
import ModelProviderDialogFooter from "./model-provider-dialog-footer";

const AnthropicSettingsDialog = ({
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

  const isAnthropicConfigured =
    settings.providers?.anthropic?.configured === true;

  const canRemoveAnthropic =
    isAnthropicConfigured &&
    (settings.providers?.openai?.configured === true ||
      settings.providers?.watsonx?.configured === true ||
      settings.providers?.ollama?.configured === true);

  const methods = useForm<AnthropicSettingsFormData>({
    mode: "onSubmit",
    defaultValues: {
      apiKey: "",
    },
  });

  useEffect(() => {
    // Reset form state on dialog open
    if (open) methods.reset();
  }, [open]);

  const { handleSubmit, watch } = methods;
  const apiKey = watch("apiKey");

  const { refetch: validateCredentials } = useGetAnthropicModelsQuery(
    {
      apiKey: apiKey,
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
        provider: "anthropic",
      };
      queryClient.setQueryData(["provider", "health"], healthData);

      toast.message("Anthropic successfully configured", {
        description: "You can now access the provided language models.",
        duration: Infinity,
        closeButton: true,
        icon: <AnthropicLogo className="w-4 h-4 text-[#D97757]" />,
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
      toast.success("Anthropic configuration removed");
      setShowRemoveConfirm(false);
      setOpen(false);
    },
  });

  const onSubmit = async (data: AnthropicSettingsFormData) => {
    // Clear any previous validation errors
    setValidationError(null);

    // Only validate if a new API key was entered
    if (data.apiKey) {
      setIsValidating(true);
      const result = await validateCredentials();
      setIsValidating(false);

      if (result.isError) {
        setValidationError(result.error);
        return;
      }
    }

    const payload: {
      anthropic_api_key?: string;
    } = {};

    // Only include api_key if a value was entered
    if (data.apiKey) {
      payload.anthropic_api_key = data.apiKey;
    }

    // Submit the update
    settingsMutation.mutate(payload);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { setShowRemoveConfirm(false); setOpen(o); }}>
      <DialogContent className="max-w-2xl">
        <FormProvider {...methods}>
          <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4">
            <DialogHeader className="mb-2">
              <DialogTitle className="flex items-center gap-3">
                <div className="w-8 h-8 rounded flex items-center justify-center bg-white border">
                  <AnthropicLogo className="text-black" />
                </div>
                Anthropic Setup
              </DialogTitle>
            </DialogHeader>

            <AnthropicSettingsForm
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
                removeMutation.mutate({ remove_anthropic_config: true })
              }
              isRemovePending={removeMutation.isPending}
              isConfigured={isAnthropicConfigured}
              canRemove={canRemoveAnthropic}
              removeDisabledTooltip="Configure another model provider before removing Anthropic"
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

export default AnthropicSettingsDialog;
