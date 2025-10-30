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
import { useOnboardingMutation } from "@/app/api/mutations/useOnboardingMutation";

const WatsonxSettingsDialog = ({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
}) => {
  const { isAuthenticated, isNoAuthMode } = useAuth();

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const isWatsonxConfigured = settings.provider?.model_provider === "watsonx";

  const methods = useForm<WatsonxSettingsFormData>({
    mode: "onChange",
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

  const onboardingMutation = useOnboardingMutation({
    onSuccess: () => {
      toast.success("watsonx settings updated successfully");
      setOpen(false);
    },
    onError: (error) => {
      toast.error("Failed to update watsonx settings", {
        description: error.message,
      });
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
    onboardingMutation.mutate(payload);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent autoFocus={false} className="max-w-2xl">
        <FormProvider {...methods}>
          <form onSubmit={handleSubmit(onSubmit)}>
            <DialogHeader className="mb-4">
              <DialogTitle className="flex items-center gap-2">
                <div className="w-8 h-8 rounded flex items-center justify-center bg-[#1063FE]">
                  <IBMLogo className="text-white" />
                </div>
                IBM watsonx.ai Setup
              </DialogTitle>
            </DialogHeader>

            <WatsonxSettingsForm isCurrentProvider={isWatsonxConfigured} />

            <DialogFooter className="mt-4">
              <Button
                variant="outline"
                type="button"
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={onboardingMutation.isPending}>
                {onboardingMutation.isPending ? "Saving..." : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </FormProvider>
      </DialogContent>
    </Dialog>
  );
};

export default WatsonxSettingsDialog;
