import { LabelWrapper } from "@/components/label-wrapper";
import OllamaLogo from "@/components/logo/ollama-logo";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useEffect, useState } from "react";
import { useUpdateSettingsMutation } from "@/app/api/mutations/useUpdateSettingsMutation";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { useForm } from "react-hook-form";
import { useGetOllamaModelsQuery } from "@/app/api/queries/useGetModelsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { useAuth } from "@/contexts/auth-context";

interface OllamaSettingsForm {
  endpoint: string;
}

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

  const {
    register,
    handleSubmit,
    watch,
    reset,
    setError,
    formState: { errors },
  } = useForm<OllamaSettingsForm>({
    mode: "onSubmit",
    defaultValues: {
      endpoint: "http://localhost:11434",
    },
  });

  const endpoint = watch("endpoint", "");
  const [isValidating, setIsValidating] = useState(false);

  // Query for validating endpoint - only enabled when we need to validate
  const { refetch: validateEndpoint } = useGetOllamaModelsQuery(
    endpoint ? { endpoint: endpoint.trim() } : undefined,
    {
      enabled: false, // Disabled by default, we'll trigger manually with refetch
      retry: false, // Don't retry on validation failure
    }
  );

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

  // Reset state when dialog opens - pre-fill with current settings
  useEffect(() => {
    if (open) {
      reset({
        endpoint: settings.provider?.endpoint || "",
      });
    }
  }, [open, reset, settings.provider?.endpoint]);

  const onSubmit = async (data: OllamaSettingsForm) => {
    setIsValidating(true);

    try {
      const result = await validateEndpoint();

      if (result.isError || !result.data) {
        setError("endpoint", {
          message: "Cannot connect to Ollama server. Check the URL and try again.",
        });
        return;
      }

      // Endpoint is valid, proceed with update
      updateSettingsMutation.mutate({
        endpoint: data.endpoint.trim(),
        model_provider: "ollama",
      });
    } catch {
      setError("endpoint", {
        message: "Failed to validate endpoint. Please try again.",
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
                <OllamaLogo />
              </div>
              Ollama Setup
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-1">
              <LabelWrapper
                label="Ollama Base URL"
                helperText="Base URL of your Ollama server"
                required
                id="endpoint"
              >
                <Input
                  {...register("endpoint", {
                    required: "Endpoint is required",
                    pattern: {
                      value: /^https?:\/\/.+/,
                      message: "Must be a valid URL (http:// or https://)",
                    },
                  })}
                  className={errors.endpoint ? "!border-destructive" : ""}
                  id="endpoint"
                  type="text"
                  placeholder="http://localhost:11434"
                />
              </LabelWrapper>
              {errors.endpoint && (
                <p className="text-sm text-destructive">
                  {errors.endpoint.message}
                </p>
              )}
            </div>
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

export default OllamaSettingsDialog;

