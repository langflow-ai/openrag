import OllamaLogo from "@/components/logo/ollama-logo";
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
  OllamaSettingsForm,
  type OllamaSettingsFormData,
} from "./ollama-settings-form";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { useAuth } from "@/contexts/auth-context";
import { useOnboardingMutation } from "@/app/api/mutations/useOnboardingMutation";

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

  const isOllamaConfigured = settings.provider?.model_provider === "ollama";

  const methods = useForm<OllamaSettingsFormData>({
    mode: "onChange",
    defaultValues: {
      endpoint: isOllamaConfigured
        ? settings.provider?.endpoint
        : "http://localhost:11434",
      llmModel: isOllamaConfigured ? settings.agent?.llm_model : "",
      embeddingModel: isOllamaConfigured
        ? settings.knowledge?.embedding_model
        : "",
    },
  });

  const { handleSubmit } = methods;

  const onboardingMutation = useOnboardingMutation({
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
    onboardingMutation.mutate({
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

export default OllamaSettingsDialog;
