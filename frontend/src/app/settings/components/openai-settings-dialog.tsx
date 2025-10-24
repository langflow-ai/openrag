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
import { useEffect, useRef, useState } from "react";
import { useUpdateSettingsMutation } from "@/app/api/mutations/useUpdateSettingsMutation";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/lib/debounce";
import { useGetOpenAIModelsQuery } from "@/app/api/queries/useGetModelsQuery";

const OpenAISettingsDialog = ({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
}) => {
  const [apiKey, setApiKey] = useState("");
  const [getFromEnv, setGetFromEnv] = useState(true);
  const inputRef = useRef<HTMLInputElement>(null);
  const debouncedApiKey = useDebouncedValue(apiKey, 500);

  // Fetch models from API when API key is provided
  const {
    data: modelsData,
    isLoading: isLoadingModels,
    error: modelsError,
  } = useGetOpenAIModelsQuery(
    getFromEnv
      ? { apiKey: "" }
      : debouncedApiKey
      ? { apiKey: debouncedApiKey }
      : undefined,
    { enabled: debouncedApiKey !== "" && !getFromEnv }
  );

  // Reset state when dialog opens/closes
  useEffect(() => {
    if (open) {
      setApiKey("");
      setGetFromEnv(true);
    }
  }, [open]);

  const updateSettingsMutation = useUpdateSettingsMutation({
    onSuccess: () => {
      toast.success("OpenAI API key updated successfully");
      setOpen(false);
    },
    onError: (error) => {
      toast.error("Failed to update API key", {
        description: error.message,
      });
    },
  });

  const handleGetFromEnvChange = (fromEnv: boolean) => {
    setGetFromEnv(fromEnv);
    if (fromEnv) {
      setApiKey("");
    }
  };

  const handleSave = () => {
    if (!getFromEnv && !apiKey.trim()) {
      inputRef.current?.focus();
      return;
    }

    updateSettingsMutation.mutate({
      api_key: getFromEnv ? "" : apiKey.trim(),
    });
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <div className="w-8 h-8 rounded flex items-center justify-center">
              <OpenAILogo />
            </div>
            OpenAI Setup
          </DialogTitle>
        </DialogHeader>

        <LabelWrapper
          label="Use environment OpenAI API key"
          id="get-api-key"
          description="Reuse the key from your environment config. Turn off to enter a different key."
          flex
        >
          <Switch
            checked={getFromEnv}
            onCheckedChange={handleGetFromEnvChange}
          />
        </LabelWrapper>
        {!getFromEnv && (
          <div className="space-y-1">
            <LabelWrapper
              label="OpenAI API key"
              helperText="Enter a new API key for your OpenAI account."
              required
              id="api-key"
            >
              <Input
                ref={inputRef}
                className={modelsError ? "!border-destructive" : ""}
                id="api-key"
                type="password"
                placeholder="sk-..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </LabelWrapper>
            {isLoadingModels && (
              <p className="text-mmd text-muted-foreground">
                Validating API key...
              </p>
            )}
            {modelsError && (
              <p className="text-mmd text-destructive">
                Invalid OpenAI API key. Verify or replace the key.
              </p>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleSave}
            disabled={updateSettingsMutation.isPending}
          >
            {updateSettingsMutation.isPending ? "Saving..." : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default OpenAISettingsDialog;
