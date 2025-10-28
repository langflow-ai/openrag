import OllamaLogo from "@/components/logo/ollama-logo";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useState } from "react";
import { useUpdateSettingsMutation } from "@/app/api/mutations/useUpdateSettingsMutation";
import { toast } from "sonner";
import { OllamaOnboarding } from "@/app/onboarding/components/ollama-onboarding";
import { OnboardingVariables } from "@/app/api/mutations/useOnboardingMutation";

const OllamaSettingsDialog = ({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
}) => {
  const [isLoadingModels, setIsLoadingModels] = useState<boolean>(false);
  const [settings, setSettings] = useState<OnboardingVariables>({
    model_provider: "ollama",
    embedding_model: "",
    llm_model: "",
  });

  // Validation state from Ollama onboarding component
  const [validationState, setValidationState] = useState({
    hasError: false,
  });

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

  const handleSave = () => {
    // Validate form
    if (
      !settings.llm_model ||
      !settings.embedding_model ||
      !settings.endpoint
    ) {
      toast.error("Please fill in all required fields");
      return;
    }

    // If there's a validation error, don't proceed
    if (isLoadingModels || validationState.hasError) {
      toast.error("Please provide a valid Ollama endpoint");
      return;
    }

    // Submit the update
    updateSettingsMutation.mutate({
      endpoint: settings.endpoint,
      model_provider: "ollama",
      llm_model: settings.llm_model,
      embedding_model: settings.embedding_model,
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent autoFocus={false} className="max-w-2xl">
        <DialogHeader className="mb-4">
          <DialogTitle className="flex items-center gap-3">
            <div className="w-8 h-8 rounded flex items-center justify-center bg-white border">
              <OllamaLogo className="text-black" />
            </div>
            Edit Ollama Setup
          </DialogTitle>
        </DialogHeader>

        <OllamaOnboarding
          setSettings={setSettings}
          sampleDataset={false}
          setSampleDataset={() => {}}
          setIsLoadingModels={setIsLoadingModels}
          onValidationChange={setValidationState}
        />

        <DialogFooter className="mt-4">
          <Button
            variant="outline"
            type="button"
            onClick={() => setOpen(false)}
          >
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={isLoadingModels || updateSettingsMutation.isPending}
          >
            {updateSettingsMutation.isPending ? "Saving..." : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default OllamaSettingsDialog;
