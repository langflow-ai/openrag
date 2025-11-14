import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { FormProvider, useForm } from "react-hook-form";
import { toast } from "sonner";
import { useUpdateSettingsMutation } from "@/app/api/mutations/useUpdateSettingsMutation";
import { useGetAnthropicModelsQuery } from "@/app/api/queries/useGetModelsQuery";
import type { ProviderHealthResponse } from "@/app/api/queries/useProviderHealthQuery";
import AnthropicLogo from "@/components/logo/anthropic-logo";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AnthropicSettingsForm,
  type AnthropicSettingsFormData,
} from "./anthropic-settings-form";

const AnthropicSettingsDialog = ({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
}) => {
  const queryClient = useQueryClient();
  const [isValidating, setIsValidating] = useState(false);
  const [validationError, setValidationError] = useState<Error | null>(null);

  const methods = useForm<AnthropicSettingsFormData>({
    mode: "onSubmit",
    defaultValues: {
      apiKey: "",
    },
  });

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

      toast.success(
        "Anthropic credentials saved. Configure models in the Settings page.",
      );
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
    <Dialog open={open} onOpenChange={setOpen}>
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
            </AnimatePresence>
            <DialogFooter className="mt-4">
              <Button
                variant="outline"
                type="button"
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={settingsMutation.isPending || isValidating}
              >
                {settingsMutation.isPending
                  ? "Saving..."
                  : isValidating
                    ? "Validating..."
                    : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </FormProvider>
      </DialogContent>
    </Dialog>
  );
};

export default AnthropicSettingsDialog;
