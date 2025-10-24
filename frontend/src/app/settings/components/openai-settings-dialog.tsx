import { LabelWrapper } from "@/components/label-wrapper";
import OpenAILogo from "@/components/logo/openai-logo";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { useEffect, useState } from "react";
import { useUpdateSettingsMutation } from "@/app/api/mutations/useUpdateSettingsMutation";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { useForm } from "react-hook-form";
import { useGetOpenAIModelsQuery } from "@/app/api/queries/useGetModelsQuery";

interface OpenAISettingsForm {
  apiKey: string;
  useEnvironmentKey: boolean;
}

const OpenAISettingsDialog = ({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
}) => {
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    reset,
    setError,
    formState: { errors },
  } = useForm<OpenAISettingsForm>({
    mode: "onSubmit",
    defaultValues: {
      apiKey: "",
      useEnvironmentKey: true,
    },
  });

  const useEnvironmentKey = watch("useEnvironmentKey", true);
  const apiKey = watch("apiKey", "");
  const [isValidating, setIsValidating] = useState(false);

  // Query for validating API key - only enabled when we need to validate
  const { refetch: validateApiKey } = useGetOpenAIModelsQuery(
    apiKey ? { apiKey: apiKey.trim() } : undefined,
    {
      enabled: false, // Disabled by default, we'll trigger manually with refetch
      retry: false, // Don't retry on validation failure
    }
  );

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

  // Reset state when dialog opens
  useEffect(() => {
    if (open) {
      reset({
        apiKey: "",
        useEnvironmentKey: true,
      });
    }
  }, [open, reset]);

  const handleUseEnvironmentKeyChange = (checked: boolean) => {
    setValue("useEnvironmentKey", checked);
    if (checked) {
      setValue("apiKey", "");
    }
  };

  const onSubmit = async (data: OpenAISettingsForm) => {
    // If using environment key, skip validation and submit directly
    if (data.useEnvironmentKey) {
      updateSettingsMutation.mutate({
        api_key: "",
        model_provider: "openai",
      });
      return;
    }

    setIsValidating(true);

    try {
      const result = await validateApiKey();

      if (result.isError || !result.data) {
        setError("apiKey", {
          message: "Invalid OpenAI API key. Verify or replace the key.",
        });
        return;
      }

      // API key is valid, proceed with update
      updateSettingsMutation.mutate({
        api_key: data.apiKey.trim(),
        model_provider: "openai",
      });
    } catch {
      setError("apiKey", {
        message: "Failed to validate API key. Please try again.",
      });
    } finally {
      setIsValidating(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent>
        <form onSubmit={handleSubmit(onSubmit)}>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <div className="w-8 h-8 rounded flex items-center justify-center">
                <OpenAILogo />
              </div>
              OpenAI Setup
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <LabelWrapper
              label="Use environment OpenAI API key"
              id="get-api-key"
              description="Use the key from your environment config. Turn off to set a new key."
              flex
            >
              <Switch
                checked={useEnvironmentKey}
                onCheckedChange={handleUseEnvironmentKeyChange}
              />
            </LabelWrapper>
            {!useEnvironmentKey && (
              <div className="space-y-1">
                <LabelWrapper
                  label="OpenAI API key"
                  helperText="Enter a new API key for your OpenAI account."
                  required
                  id="api-key"
                >
                  <Input
                    {...register("apiKey", {
                      required: !useEnvironmentKey && "API key is required",
                    })}
                    className={errors.apiKey ? "!border-destructive" : ""}
                    id="api-key"
                    type="password"
                    placeholder="sk-..."
                  />
                </LabelWrapper>
                {errors.apiKey && (
                  <p className="text-sm text-destructive">
                    {errors.apiKey.message}
                  </p>
                )}
              </div>
            )}
          </div>

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
              disabled={isValidating || updateSettingsMutation.isPending}
            >
              {isValidating
                ? "Validating..."
                : updateSettingsMutation.isPending
                ? "Saving..."
                : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export default OpenAISettingsDialog;
