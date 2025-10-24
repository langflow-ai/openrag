import { LabelWrapper } from "@/components/label-wrapper";
import IBMLogo from "@/components/logo/ibm-logo";
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
import { useGetIBMModelsQuery } from "@/app/api/queries/useGetModelsQuery";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { useAuth } from "@/contexts/auth-context";

interface WatsonxSettingsForm {
  endpoint: string;
  apiKey: string;
  projectId: string;
}

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

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    reset,
    setError,
    formState: { errors },
  } = useForm<WatsonxSettingsForm>({
    mode: "onSubmit",
    defaultValues: {
      endpoint: "https://us-south.ml.cloud.ibm.com",
      apiKey: "",
      projectId: "",
    },
  });

  const endpoint = watch("endpoint", "");
  const apiKey = watch("apiKey", "");
  const projectId = watch("projectId", "");
  const [isValidating, setIsValidating] = useState(false);

  const endpointOptions = [
    { value: "https://us-south.ml.cloud.ibm.com", label: "https://us-south.ml.cloud.ibm.com" },
    { value: "https://eu-de.ml.cloud.ibm.com", label: "https://eu-de.ml.cloud.ibm.com" },
    { value: "https://eu-gb.ml.cloud.ibm.com", label: "https://eu-gb.ml.cloud.ibm.com" },
    { value: "https://au-syd.ml.cloud.ibm.com", label: "https://au-syd.ml.cloud.ibm.com" },
    { value: "https://jp-tok.ml.cloud.ibm.com", label: "https://jp-tok.ml.cloud.ibm.com" },
    { value: "https://ca-tor.ml.cloud.ibm.com", label: "https://ca-tor.ml.cloud.ibm.com" },
  ];

  // Query for validating credentials - only enabled when we need to validate
  const { refetch: validateCredentials } = useGetIBMModelsQuery(
    endpoint && apiKey && projectId
      ? {
          endpoint: endpoint.trim(),
          apiKey: apiKey.trim(),
          projectId: projectId.trim(),
        }
      : undefined,
    {
      enabled: false, // Disabled by default, we'll trigger manually with refetch
      retry: false, // Don't retry on validation failure
    }
  );

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

  // Reset state when dialog opens - pre-fill with current settings
  useEffect(() => {
    if (open) {
      reset({
        endpoint: settings.provider?.endpoint || "",
        apiKey: "",
        projectId: settings.provider?.project_id || "",
      });
    }
  }, [open, reset, settings.provider?.endpoint, settings.provider?.project_id]);

  const onSubmit = async (data: WatsonxSettingsForm) => {
    setIsValidating(true);

    try {
      const result = await validateCredentials();

      if (result.isError || !result.data) {
        setError("apiKey", {
          message: "Invalid credentials. Check your API key, project ID, and endpoint.",
        });
        return;
      }

      // Credentials are valid, proceed with update
      updateSettingsMutation.mutate({
        endpoint: data.endpoint.trim(),
        api_key: data.apiKey.trim(),
        project_id: data.projectId.trim(),
        model_provider: "watsonx",
      });
    } catch {
      setError("apiKey", {
        message: "Failed to validate credentials. Please try again.",
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
                <IBMLogo />
              </div>
              watsonx Setup
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-1">
              <LabelWrapper
                label="watsonx.ai API Endpoint"
                helperText="Base URL of the API"
                required
                id="endpoint"
              >
                <Select
                  value={endpoint}
                  onValueChange={(value) => setValue("endpoint", value)}
                >
                  <SelectTrigger id="endpoint">
                    <SelectValue placeholder="Select endpoint..." />
                  </SelectTrigger>
                  <SelectContent>
                    {endpointOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </LabelWrapper>
            </div>

            <div className="space-y-1">
              <LabelWrapper
                label="watsonx Project ID"
                helperText="Project ID for the model"
                required
                id="project-id"
              >
                <Input
                  {...register("projectId", {
                    required: "Project ID is required",
                  })}
                  className={errors.projectId ? "!border-destructive" : ""}
                  id="project-id"
                  type="text"
                  placeholder="your-project-id"
                />
              </LabelWrapper>
              {errors.projectId && (
                <p className="text-sm text-destructive">
                  {errors.projectId.message}
                </p>
              )}
            </div>

            <div className="space-y-1">
              <LabelWrapper
                label="watsonx API key"
                helperText="API key to access watsonx.ai"
                required
                id="api-key"
              >
                <Input
                  {...register("apiKey", {
                    required: "API key is required",
                  })}
                  className={errors.apiKey ? "!border-destructive" : ""}
                  id="api-key"
                  type="password"
                  placeholder="your-api-key"
                />
              </LabelWrapper>
              {errors.apiKey && (
                <p className="text-sm text-destructive">
                  {errors.apiKey.message}
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

export default WatsonxSettingsDialog;

