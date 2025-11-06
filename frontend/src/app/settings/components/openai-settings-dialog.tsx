import OpenAILogo from "@/components/logo/openai-logo";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FormProvider, useForm } from "react-hook-form";
import { toast } from "sonner";
import {
  OpenAISettingsForm,
  type OpenAISettingsFormData,
} from "./openai-settings-form";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { useAuth } from "@/contexts/auth-context";
import { useUpdateSettingsMutation } from "@/app/api/mutations/useUpdateSettingsMutation";
import { AnimatePresence, motion } from "motion/react";
import { useQueryClient } from "@tanstack/react-query";
import type { ProviderHealthResponse } from "@/app/api/queries/useProviderHealthQuery";

const OpenAISettingsDialog = ({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
}) => {
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const queryClient = useQueryClient();

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const isOpenAIConfigured = settings.provider?.model_provider === "openai";

  const methods = useForm<OpenAISettingsFormData>({
    mode: "onSubmit",
    defaultValues: {
      apiKey: "",
      llmModel: isOpenAIConfigured ? settings.agent?.llm_model : "",
      embeddingModel: isOpenAIConfigured
        ? settings.knowledge?.embedding_model
        : "",
    },
  });

  const { handleSubmit } = methods;

  const settingsMutation = useUpdateSettingsMutation({
    onSuccess: () => {
      // Update provider health cache to healthy since backend validated the setup
      const healthData: ProviderHealthResponse = {
        status: "healthy",
        message: "Provider is configured and working correctly",
        provider: "openai",
      };
      queryClient.setQueryData(["provider", "health"], healthData);

      toast.success("OpenAI settings updated successfully");
      setOpen(false);
    },
  });

  const onSubmit = (data: OpenAISettingsFormData) => {
    const payload: {
      api_key?: string;
      model_provider: string;
      llm_model: string;
      embedding_model: string;
    } = {
      model_provider: "openai",
      llm_model: data.llmModel,
      embedding_model: data.embeddingModel,
    };

    // Only include api_key if a value was entered
    if (data.apiKey) {
      payload.api_key = data.apiKey;
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
                  <OpenAILogo className="text-black" />
                </div>
                OpenAI Setup
              </DialogTitle>
            </DialogHeader>

            <OpenAISettingsForm isCurrentProvider={isOpenAIConfigured} />

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
              <Button type="submit" disabled={settingsMutation.isPending}>
                {settingsMutation.isPending ? "Saving..." : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </FormProvider>
      </DialogContent>
    </Dialog>
  );
};

export default OpenAISettingsDialog;
