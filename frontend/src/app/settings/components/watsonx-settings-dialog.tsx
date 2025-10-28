import IBMLogo from "@/components/logo/ibm-logo";
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
import { IBMOnboarding } from "@/app/onboarding/components/ibm-onboarding";
import { OnboardingVariables } from "@/app/api/mutations/useOnboardingMutation";

const WatsonxSettingsDialog = ({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
}) => {
  const [isLoadingModels, setIsLoadingModels] = useState<boolean>(false);
  const [settings, setSettings] = useState<OnboardingVariables>({
    model_provider: "watsonx",
    embedding_model: "",
    llm_model: "",
  });

  // Validation state from IBM onboarding component
  const [validationState, setValidationState] = useState({
    hasError: false,
  });

  const updateSettingsMutation = useUpdateSettingsMutation({
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

  const handleSave = () => {
    // Validate form
    if (
      !settings.llm_model ||
      !settings.embedding_model ||
      !settings.endpoint ||
      !settings.project_id ||
      !settings.api_key
    ) {
      toast.error("Please fill in all required fields");
      return;
    }

    // If there's a validation error, don't proceed
    if (isLoadingModels || validationState.hasError) {
      toast.error("Please provide valid watsonx credentials");
      return;
    }

    // Submit the update
    updateSettingsMutation.mutate({
      endpoint: settings.endpoint,
      api_key: settings.api_key,
      project_id: settings.project_id,
      model_provider: "watsonx",
      llm_model: settings.llm_model,
      embedding_model: settings.embedding_model,
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent autoFocus={false} className="max-w-2xl">
        <DialogHeader className="mb-4">
          <DialogTitle className="flex items-center gap-2">
            <div className="w-8 h-8 rounded flex items-center justify-center bg-[#1063FE]">
              <IBMLogo className="text-white" />
            </div>
            IBM watsonx.ai Setup
          </DialogTitle>
        </DialogHeader>

        <IBMOnboarding
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

export default WatsonxSettingsDialog;
