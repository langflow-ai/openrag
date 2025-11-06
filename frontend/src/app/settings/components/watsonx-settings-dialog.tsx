import IBMLogo from "@/components/logo/ibm-logo";
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
  WatsonxSettingsForm,
  type WatsonxSettingsFormData,
} from "./watsonx-settings-form";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { useAuth } from "@/contexts/auth-context";
import { useUpdateSettingsMutation } from "@/app/api/mutations/useUpdateSettingsMutation";
import { useQueryClient } from "@tanstack/react-query";
import type { ProviderHealthResponse } from "@/app/api/queries/useProviderHealthQuery";
import { AnimatePresence, motion } from "motion/react";

const WatsonxSettingsDialog = ({
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

  const isWatsonxConfigured = settings.provider?.model_provider === "watsonx";

  const methods = useForm<WatsonxSettingsFormData>({
    mode: "onSubmit",
    defaultValues: {
      endpoint: isWatsonxConfigured
        ? settings.provider?.endpoint
        : "https://us-south.ml.cloud.ibm.com",
      apiKey: "",
      projectId: isWatsonxConfigured ? settings.provider?.project_id : "",
      llmModel: isWatsonxConfigured ? settings.agent?.llm_model : "",
      embeddingModel: isWatsonxConfigured
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
        provider: "watsonx",
      };
      queryClient.setQueryData(["provider", "health"], healthData);
      toast.success("watsonx settings updated successfully");
      setOpen(false);
    },
  });

  const onSubmit = (data: WatsonxSettingsFormData) => {
    const payload: {
      endpoint: string;
      api_key?: string;
      project_id: string;
      model_provider: string;
      llm_model: string;
      embedding_model: string;
    } = {
      endpoint: data.endpoint,
      project_id: data.projectId,
      model_provider: "watsonx",
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
      <DialogContent autoFocus={false} className="max-w-2xl">
        <FormProvider {...methods}>
          <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4">
            <DialogHeader className="mb-2">
              <DialogTitle className="flex items-center gap-3">
                <div className="w-8 h-8 rounded flex items-center justify-center bg-white border">
                  <IBMLogo className="text-black" />
                </div>
                IBM watsonx.ai Setup
              </DialogTitle>
            </DialogHeader>

            <WatsonxSettingsForm isCurrentProvider={isWatsonxConfigured} />
           
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
            <DialogFooter>
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

export default WatsonxSettingsDialog;
