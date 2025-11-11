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
import { useGetIBMModelsQuery } from "@/app/api/queries/useGetModelsQuery";
import { useUpdateSettingsMutation } from "@/app/api/mutations/useUpdateSettingsMutation";
import { useQueryClient } from "@tanstack/react-query";
import type { ProviderHealthResponse } from "@/app/api/queries/useProviderHealthQuery";
import { AnimatePresence, motion } from "motion/react";
import { useDebouncedValue } from "@/lib/debounce";

const WatsonxSettingsDialog = ({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
}) => {
  const queryClient = useQueryClient();

  const methods = useForm<WatsonxSettingsFormData>({
    mode: "onSubmit",
    defaultValues: {
      endpoint: "https://us-south.ml.cloud.ibm.com",
      apiKey: "",
      projectId: "",
    },
  });

  const { handleSubmit, watch, formState } = methods;
  const endpoint = watch("endpoint");
  const apiKey = watch("apiKey");
  const projectId = watch("projectId");

  const debouncedEndpoint = useDebouncedValue(endpoint, 500);
  const debouncedApiKey = useDebouncedValue(apiKey, 500);
  const debouncedProjectId = useDebouncedValue(projectId, 500);

  const {
    isLoading: isLoadingModels,
    error: modelsError,
  } = useGetIBMModelsQuery(
    {
      endpoint: debouncedEndpoint,
      apiKey: debouncedApiKey,
      projectId: debouncedProjectId,
    },
    {
      enabled: !!debouncedEndpoint && !!debouncedApiKey && !!debouncedProjectId && open,
    }
  );

  const hasValidationError = !!modelsError || !!formState.errors.endpoint || !!formState.errors.apiKey || !!formState.errors.projectId;

  const settingsMutation = useUpdateSettingsMutation({
    onSuccess: () => {
      // Update provider health cache to healthy since backend validated the setup
      const healthData: ProviderHealthResponse = {
        status: "healthy",
        message: "Provider is configured and working correctly",
        provider: "watsonx",
      };
      queryClient.setQueryData(["provider", "health"], healthData);
      toast.success("watsonx credentials saved. Configure models in the Settings page.");
      setOpen(false);
    },
  });

  const onSubmit = (data: WatsonxSettingsFormData) => {
    const payload: {
      watsonx_endpoint: string;
      watsonx_api_key?: string;
      watsonx_project_id: string;
    } = {
      watsonx_endpoint: data.endpoint,
      watsonx_project_id: data.projectId,
    };

    // Only include api_key if a value was entered
    if (data.apiKey) {
      payload.watsonx_api_key = data.apiKey;
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

            <WatsonxSettingsForm
              modelsError={modelsError}
              isLoadingModels={isLoadingModels}
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
            <DialogFooter>
              <Button
                variant="outline"
                type="button"
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={settingsMutation.isPending || hasValidationError || isLoadingModels}
              >
                {settingsMutation.isPending ? "Saving..." : isLoadingModels ? "Validating..." : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </FormProvider>
      </DialogContent>
    </Dialog>
  );
};

export default WatsonxSettingsDialog;
