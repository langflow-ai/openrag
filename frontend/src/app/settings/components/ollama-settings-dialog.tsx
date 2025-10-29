import OllamaLogo from "@/components/logo/ollama-logo";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useEffect } from "react";
import { FormProvider, useForm } from "react-hook-form";
import { useUpdateSettingsMutation } from "@/app/api/mutations/useUpdateSettingsMutation";
import { toast } from "sonner";
import {
  OllamaSettingsForm,
  type OllamaSettingsFormData,
} from "./ollama-settings-form";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { useAuth } from "@/contexts/auth-context";

const OllamaSettingsDialog = ({
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

  const methods = useForm<OllamaSettingsFormData>({
    mode: "onChange",
    defaultValues: {
      endpoint: "",
      llmModel: "",
      embeddingModel: "",
    },
  });

  const { handleSubmit, reset, formState } = methods;

  // Initialize form from settings when dialog opens or settings change
  useEffect(() => {
    if (open && settings) {
      reset({
        endpoint: settings.provider?.endpoint || "http://localhost:11434",
        llmModel: settings.agent?.llm_model || "",
        embeddingModel: settings.knowledge?.embedding_model || "",
      });
    }
  }, [open, settings, reset]);

  const updateSettingsMutation = useUpdateSettingsMutation({
    onSuccess: () => {
      toast.success("Ollama settings updated successfully");
      setOpen(false);
    },
    onError: (error) => {
      toast.error("Failed to update Ollama settings", {
        description: error.message,
      });
    },
  });

  const onSubmit = (data: OllamaSettingsFormData) => {
    // Submit the update
    updateSettingsMutation.mutate({
      endpoint: data.endpoint,
      model_provider: "ollama",
      llm_model: data.llmModel,
      embedding_model: data.embeddingModel,
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent autoFocus={false} className="max-w-2xl">
        <FormProvider {...methods}>
          <form onSubmit={handleSubmit(onSubmit)}>
            <DialogHeader className="mb-4">
              <DialogTitle className="flex items-center gap-3">
                <div className="w-8 h-8 rounded flex items-center justify-center bg-white border">
                  <OllamaLogo className="text-black" />
                </div>
                Ollama Setup
              </DialogTitle>
            </DialogHeader>

            <OllamaSettingsForm />

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
                disabled={
                  !formState.isValid || updateSettingsMutation.isPending
                }
              >
                {updateSettingsMutation.isPending ? "Saving..." : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </FormProvider>
      </DialogContent>
    </Dialog>
  );
};

export default OllamaSettingsDialog;
