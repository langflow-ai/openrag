import OpenAILogo from "@/components/logo/openai-logo";
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
import { OpenAIOnboarding } from "@/app/onboarding/components/openai-onboarding";
import { OnboardingVariables } from "@/app/api/mutations/useOnboardingMutation";

const OpenAISettingsDialog = ({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
}) => {
  const [isLoadingModels, setIsLoadingModels] = useState<boolean>(false);
  const [settings, setSettings] = useState<OnboardingVariables>({
    model_provider: "openai",
    embedding_model: "",
    llm_model: "",
  });

  // Validation state from OpenAI onboarding component
  const [validationState, setValidationState] = useState({
    getFromEnv: true,
    hasError: false,
  });

  const updateSettingsMutation = useUpdateSettingsMutation({
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

  const handleSave = () => {
    // Validate form
    if (
      !settings.llm_model ||
      !settings.embedding_model ||
      (!validationState.getFromEnv && !settings.api_key)
    ) {
      toast.error("Please fill in all required fields");
      return;
    }

    // If not using env key and there's a validation error, don't proceed
    if (
      isLoadingModels ||
      (!validationState.getFromEnv && validationState.hasError)
    ) {
      toast.error("Please provide a valid API key");
      return;
    }

    // Submit the update
    updateSettingsMutation.mutate({
      api_key: settings.api_key,
      model_provider: "openai",
      llm_model: settings.llm_model,
      embedding_model: settings.embedding_model,
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent autoFocus={false} className="max-w-2xl">
        <DialogHeader className="mb-4">
          <DialogTitle className="flex items-center gap-2">
            <div className="w-8 h-8 rounded flex items-center justify-center bg-white border">
              <OpenAILogo className="text-black" />
            </div>
            OpenAI Setup
          </DialogTitle>
        </DialogHeader>

        <OpenAIOnboarding
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

export default OpenAISettingsDialog;
