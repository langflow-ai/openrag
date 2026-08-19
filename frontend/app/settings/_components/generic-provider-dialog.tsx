"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { useUpdateSettingsMutation } from "@/app/api/mutations/useUpdateSettingsMutation";
import {
  type CatalogCredentialField,
  useGetModelCatalogQuery,
} from "@/app/api/queries/useGetModelsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { LabelWrapper } from "@/components/label-wrapper";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ModelSelector } from "../../onboarding/_components/model-selector";
import { getModelLogo } from "../_helpers/model-helpers";

const SECRET_TYPES = new Set(["password", "textarea", "upload"]);

function optionsFor(field: CatalogCredentialField): string[] {
  if (!Array.isArray(field.options)) return [];
  return field.options.flatMap((option) =>
    typeof option === "string" ? [option] : [],
  );
}

export function GenericProviderDialog({
  open,
  onOpenChange,
  initialProvider,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialProvider?: string;
}) {
  const { data: catalog } = useGetModelCatalogQuery();
  const { data: settings } = useGetSettingsQuery();
  const [provider, setProvider] = useState(initialProvider ?? "");
  const [values, setValues] = useState<Record<string, string>>({});
  const [testModel, setTestModel] = useState("");

  const providerEntry = catalog?.providers.find(
    (entry) => entry.key === provider,
  );
  const fields = providerEntry?.credential_fields ?? [];
  const saved = settings?.providers?.custom?.[provider];
  const savedSecrets = useMemo(
    () => new Set(saved?.secret_fields ?? []),
    [saved?.secret_fields],
  );

  useEffect(() => {
    if (!open) return;
    setProvider(initialProvider ?? "");
    setValues({});
    setValidationError(null);
  }, [initialProvider, open]);

  useEffect(() => {
    if (!providerEntry) {
      setTestModel("");
      return;
    }
    // Prefer a real catalogue model; fall back to the provider's placeholder
    // (e.g. "your-deployment-name" for Azure) so the field shows the shape
    // the provider expects rather than an empty box.
    setTestModel(
      providerEntry.models?.[0]?.model ??
        providerEntry.embedding_models?.[0]?.model ??
        "",
    );
  }, [providerEntry]);

  useEffect(() => {
    if (!providerEntry) return;
    setValues(() => {
      const next = { ...(saved?.credential_values ?? {}) };
      for (const field of providerEntry.credential_fields) {
        if (
          next[field.key] === undefined &&
          typeof field.default_value === "string"
        ) {
          next[field.key] = field.default_value;
        }
      }
      return next;
    });
  }, [providerEntry, saved?.credential_values]);

  // Credentials are saved first, then verified with a real call through
  // LiteLLM. Saving alone proves nothing — a wrong Azure api_base or a
  // deployment name that does not exist only fails later, mid-chat or
  // mid-ingest, as "AzureException APIError - Resource not found".
  const [validationError, setValidationError] = useState<string | null>(null);
  const [isValidating, setIsValidating] = useState(false);

  const validateProvider = async () => {
    setIsValidating(true);
    setValidationError(null);
    try {
      const url = new URL("/api/provider/health", window.location.origin);
      url.searchParams.set("provider", provider);
      if (testModel.trim()) url.searchParams.set("model", testModel.trim());

      const response = await fetch(url.toString());
      if (response.ok) {
        toast.success(`${providerEntry?.name ?? provider} configured`);
        onOpenChange(false);
        return;
      }
      const body = await response.json().catch(() => ({}));
      setValidationError(
        body.message ||
          "The provider was saved but could not be verified. Check the credentials and model name.",
      );
    } catch (error) {
      setValidationError(
        error instanceof Error ? error.message : "Validation request failed",
      );
    } finally {
      setIsValidating(false);
    }
  };

  const mutation = useUpdateSettingsMutation({
    onSuccess: () => {
      void validateProvider();
    },
    onError: (error) => {
      toast.error("Failed to configure provider", {
        description: error.message,
      });
    },
  });

  const ready =
    provider !== "" &&
    fields
      .filter((field) => field.required)
      .every(
        (field) =>
          Boolean(values[field.key]?.trim()) || savedSecrets.has(field.key),
      );

  const providerOptions =
    catalog?.providers.map((entry) => ({
      value: entry.key,
      label: entry.name,
      provider: entry.key,
      icon: getModelLogo("", entry.key),
    })) ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Configure model provider</DialogTitle>
        </DialogHeader>
        <LabelWrapper
          id="provider-picker"
          label="Provider"
          helperText="Every provider supported by the installed LiteLLM version"
          required
        >
          <ModelSelector
            options={providerOptions}
            value={provider}
            onValueChange={(value) => setProvider(value)}
            searchPlaceholder="Search providers..."
            placeholder="Select provider..."
          />
        </LabelWrapper>

        {provider && (
          <div className="grid gap-4 sm:grid-cols-2">
            {fields.map((field) => {
              const id = `provider-${field.key}`;
              const value = values[field.key] ?? "";
              const setValue = (next: string) =>
                setValues((previous) => ({
                  ...previous,
                  [field.key]: next,
                }));
              const options = optionsFor(field);
              const configuredSecret =
                savedSecrets.has(field.key) && value === "";

              if (field.field_type === "select" && options.length > 0) {
                return (
                  <LabelWrapper
                    key={field.key}
                    id={id}
                    label={field.label}
                    helperText={field.tooltip}
                    required={field.required}
                  >
                    <Select value={value} onValueChange={setValue}>
                      <SelectTrigger id={id}>
                        <SelectValue placeholder={field.placeholder ?? ""} />
                      </SelectTrigger>
                      <SelectContent>
                        {options.map((option) => (
                          <SelectItem key={option} value={option}>
                            {option}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </LabelWrapper>
                );
              }

              const Control =
                field.field_type === "textarea" || field.field_type === "upload"
                  ? Textarea
                  : Input;
              return (
                <LabelWrapper
                  key={field.key}
                  id={id}
                  label={field.label}
                  helperText={field.tooltip}
                  required={field.required}
                >
                  <div className="space-y-1">
                    <Control
                      id={id}
                      type={
                        Control === Input && SECRET_TYPES.has(field.field_type)
                          ? "password"
                          : undefined
                      }
                      value={value}
                      placeholder={
                        configuredSecret
                          ? "Configured secret (leave blank to reuse)"
                          : (field.placeholder ?? undefined)
                      }
                      onChange={(event) => setValue(event.target.value)}
                    />
                    {configuredSecret && (
                      <p className="text-mmd text-muted-foreground">
                        Leave blank to reuse the configured secret.
                      </p>
                    )}
                  </div>
                </LabelWrapper>
              );
            })}
          </div>
        )}

        {provider && (
          <LabelWrapper
            id="provider-test-model"
            label="Model to verify with"
            helperText={
              providerEntry?.model_placeholder
                ? `Used once to confirm the credentials work. e.g. ${providerEntry.model_placeholder}`
                : "Used once to confirm the credentials work. For providers with per-account deployments (Azure, Bedrock, SageMaker) enter your own deployment name."
            }
          >
            <Input
              id="provider-test-model"
              value={testModel}
              placeholder={providerEntry?.model_placeholder ?? "model name"}
              onChange={(event) => setTestModel(event.target.value)}
            />
          </LabelWrapper>
        )}

        {validationError && (
          <div
            data-testid="provider-validation-error"
            className="border border-destructive/40 bg-destructive/10 p-3 text-mmd"
          >
            <p className="font-medium">
              Saved, but the provider did not respond
            </p>
            <p className="mt-1 break-words text-muted-foreground">
              {validationError}
            </p>
          </div>
        )}

        <DialogFooter>
          {saved?.configured &&
            !["openai", "anthropic", "ollama", "watsonx"].includes(
              provider,
            ) && (
              <Button
                variant="destructive"
                onClick={() =>
                  mutation.mutate({ remove_provider_config: provider })
                }
              >
                Remove
              </Button>
            )}
          <Button
            disabled={!ready || isValidating}
            loading={mutation.isPending || isValidating}
            onClick={() =>
              mutation.mutate({
                provider_credentials: {
                  [provider]: Object.fromEntries(
                    Object.entries(values).filter(([, value]) => value.trim()),
                  ),
                },
              })
            }
          >
            {isValidating ? "Verifying..." : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
