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

const OpenAISettingsDialog = ({
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
      toast.success("OpenAI settings updated successfully");
      setOpen(false);
    },
    onError: (error) => {
      toast.error("Failed to update OpenAI settings", {
        description: error.message,
      });
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

export default OpenAISettingsDialog;
