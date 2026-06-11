"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { LabelWrapper } from "@/components/label-wrapper";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NumberInput } from "@/components/ui/inputs/number-input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { cn } from "@/lib/utils";
import { useUpdateSettingsMutation } from "../../api/mutations/useUpdateSettingsMutation";

const DEFAULT_OPENAI_URL = "https://api.openai.com/v1/chat/completions";
const DEFAULT_WATSONX_API_VERSION = "2023-05-29";

const RESPONSE_FORMATS = [
  { value: "markdown", label: "Markdown (recommended)" },
  { value: "doctags", label: "DocTags" },
  { value: "html", label: "HTML" },
] as const;

export function DoclingVlmSettingsSection() {
  const isCloudBrand = useIsCloudBrand();
  const { isAuthenticated, isNoAuthMode } = useAuth();

  const [vlmEnabled, setVlmEnabled] = useState<boolean>(false);
  const [vlmProvider, setVlmProvider] = useState<string>("openai");
  const [vlmModel, setVlmModel] = useState<string>("");
  const [vlmPrompt, setVlmPrompt] = useState<string>("");
  const [vlmResponseFormat, setVlmResponseFormat] =
    useState<string>("markdown");
  const [vlmMaxTokens, setVlmMaxTokens] = useState<number>(5000);
  const [vlmConcurrency, setVlmConcurrency] = useState<number>(4);
  const [vlmTimeout, setVlmTimeout] = useState<number>(120);
  const [vlmOpenaiUrl, setVlmOpenaiUrl] = useState<string>(DEFAULT_OPENAI_URL);
  const [vlmWatsonxApiVersion, setVlmWatsonxApiVersion] = useState<string>(
    DEFAULT_WATSONX_API_VERSION,
  );
  const [validationError, setValidationError] = useState<string | null>(null);

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const updateSettingsMutation = useUpdateSettingsMutation({
    onSuccess: () => {
      toast.success("Docling VLM settings updated successfully");
    },
    onError: (error) => {
      toast.error("Failed to update settings", { description: error.message });
    },
  });

  const k = settings.knowledge;

  useEffect(() => {
    if (k?.vlm_enabled !== undefined) setVlmEnabled(k.vlm_enabled);
  }, [k?.vlm_enabled]);
  useEffect(() => {
    if (k?.vlm_provider !== undefined) setVlmProvider(k.vlm_provider);
  }, [k?.vlm_provider]);
  useEffect(() => {
    if (k?.vlm_model !== undefined) setVlmModel(k.vlm_model);
  }, [k?.vlm_model]);
  useEffect(() => {
    if (k?.vlm_prompt !== undefined) setVlmPrompt(k.vlm_prompt);
  }, [k?.vlm_prompt]);
  useEffect(() => {
    if (k?.vlm_response_format !== undefined)
      setVlmResponseFormat(k.vlm_response_format);
  }, [k?.vlm_response_format]);
  useEffect(() => {
    if (k?.vlm_max_tokens !== undefined) setVlmMaxTokens(k.vlm_max_tokens);
  }, [k?.vlm_max_tokens]);
  useEffect(() => {
    if (k?.vlm_concurrency !== undefined) setVlmConcurrency(k.vlm_concurrency);
  }, [k?.vlm_concurrency]);
  useEffect(() => {
    if (k?.vlm_timeout !== undefined) setVlmTimeout(k.vlm_timeout);
  }, [k?.vlm_timeout]);
  useEffect(() => {
    if (k?.vlm_openai_url !== undefined) setVlmOpenaiUrl(k.vlm_openai_url);
  }, [k?.vlm_openai_url]);
  useEffect(() => {
    if (k?.vlm_watsonx_api_version !== undefined)
      setVlmWatsonxApiVersion(k.vlm_watsonx_api_version);
  }, [k?.vlm_watsonx_api_version]);

  const vlmDirty =
    vlmEnabled !== (k?.vlm_enabled ?? vlmEnabled) ||
    vlmProvider !== (k?.vlm_provider ?? vlmProvider) ||
    vlmModel !== (k?.vlm_model ?? vlmModel) ||
    vlmPrompt !== (k?.vlm_prompt ?? vlmPrompt) ||
    vlmResponseFormat !== (k?.vlm_response_format ?? vlmResponseFormat) ||
    vlmMaxTokens !== (k?.vlm_max_tokens ?? vlmMaxTokens) ||
    vlmConcurrency !== (k?.vlm_concurrency ?? vlmConcurrency) ||
    vlmTimeout !== (k?.vlm_timeout ?? vlmTimeout) ||
    vlmOpenaiUrl !== (k?.vlm_openai_url ?? vlmOpenaiUrl) ||
    vlmWatsonxApiVersion !==
      (k?.vlm_watsonx_api_version ?? vlmWatsonxApiVersion);

  // settings.providers is null when the caller lacks providers:read; treat
  // that as unknown and let the backend reject invalid saves instead.
  const providerConfigured =
    settings.providers === undefined || settings.providers === null
      ? undefined
      : vlmProvider === "watsonx"
        ? settings.providers.watsonx?.configured === true
        : settings.providers.openai?.configured === true;
  const providerWarning = vlmEnabled && providerConfigured === false;
  const providerLabel = vlmProvider === "watsonx" ? "IBM watsonx.ai" : "OpenAI";

  const handleSave = () => {
    if (vlmEnabled && !vlmModel.trim()) {
      const msg = "Model name is required when VLM ingestion is enabled";
      setValidationError(msg);
      toast.error("Could not save Docling VLM settings", { description: msg });
      return;
    }
    if (vlmMaxTokens < 1 || vlmConcurrency < 1 || vlmTimeout < 1) {
      const msg = "Max tokens, concurrency, and timeout must be at least 1";
      setValidationError(msg);
      toast.error("Could not save Docling VLM settings", { description: msg });
      return;
    }
    updateSettingsMutation.mutate(
      {
        vlm_enabled: vlmEnabled,
        vlm_provider: vlmProvider,
        ...(vlmModel.trim() ? { vlm_model: vlmModel.trim() } : {}),
        vlm_prompt: vlmPrompt,
        vlm_response_format: vlmResponseFormat,
        vlm_max_tokens: vlmMaxTokens,
        vlm_concurrency: vlmConcurrency,
        vlm_timeout: vlmTimeout,
        ...(vlmProvider === "openai" && vlmOpenaiUrl.trim()
          ? { vlm_openai_url: vlmOpenaiUrl.trim() }
          : {}),
        ...(vlmProvider === "watsonx" && vlmWatsonxApiVersion.trim()
          ? { vlm_watsonx_api_version: vlmWatsonxApiVersion.trim() }
          : {}),
      },
      { onSuccess: () => setValidationError(null) },
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle
          className={cn(
            "text-lg",
            isCloudBrand && "ibm-settings-section-title",
          )}
        >
          Docling VLM
        </CardTitle>
        <CardDescription>
          Process documents with a remote vision language model instead of the
          standard Docling pipeline. Each page is sent to the selected
          provider&apos;s vision model; the rest of ingestion (chunking,
          embedding, indexing) is unchanged. Credentials are reused from
          Settings &gt; Providers.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          <div className="flex items-center justify-between py-3 border-b border-border">
            <div className="flex-1">
              <Label
                htmlFor="vlm-enabled"
                className="text-base font-medium cursor-pointer pb-3"
              >
                Use VLM for ingestion
              </Label>
              <div className="text-sm text-muted-foreground">
                Requires docling-serve started with remote services enabled
                (restart docling-serve after upgrading). Ingest is slower and
                incurs per-page model costs.
              </div>
            </div>
            <Switch
              id="vlm-enabled"
              checked={vlmEnabled}
              onCheckedChange={setVlmEnabled}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <LabelWrapper id="vlm-provider" label="Provider">
                <Select value={vlmProvider} onValueChange={setVlmProvider}>
                  <SelectTrigger id="vlm-provider">
                    <SelectValue placeholder="Select a provider" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="openai">OpenAI</SelectItem>
                    <SelectItem value="watsonx">IBM watsonx.ai</SelectItem>
                  </SelectContent>
                </Select>
              </LabelWrapper>
              {providerWarning && (
                <p className="text-sm text-destructive" role="alert">
                  {providerLabel} is not configured. Configure it in Settings
                  &gt; Providers first.
                </p>
              )}
            </div>
            <div className="space-y-2">
              <LabelWrapper id="vlm-model" label="Model" required={vlmEnabled}>
                <Input
                  id="vlm-model"
                  type="text"
                  placeholder={
                    vlmProvider === "watsonx"
                      ? "e.g. meta-llama/llama-3-2-11b-vision-instruct"
                      : "e.g. gpt-4o"
                  }
                  value={vlmModel}
                  onChange={(e) => {
                    setVlmModel(e.target.value);
                    setValidationError(null);
                  }}
                  className={validationError ? "border-destructive" : ""}
                />
              </LabelWrapper>
            </div>
          </div>

          {vlmProvider === "openai" ? (
            <div className="space-y-2">
              <LabelWrapper
                id="vlm-openai-url"
                label="Chat completions URL"
                helperText="Override for OpenAI-compatible endpoints"
              >
                <Input
                  id="vlm-openai-url"
                  type="text"
                  placeholder={DEFAULT_OPENAI_URL}
                  value={vlmOpenaiUrl}
                  onChange={(e) => setVlmOpenaiUrl(e.target.value)}
                />
              </LabelWrapper>
            </div>
          ) : (
            <div className="space-y-2">
              <LabelWrapper
                id="vlm-watsonx-api-version"
                label="watsonx API version"
                helperText="API version date sent to watsonx.ai"
              >
                <Input
                  id="vlm-watsonx-api-version"
                  type="text"
                  placeholder={DEFAULT_WATSONX_API_VERSION}
                  value={vlmWatsonxApiVersion}
                  onChange={(e) => setVlmWatsonxApiVersion(e.target.value)}
                />
              </LabelWrapper>
            </div>
          )}

          <div className="space-y-2">
            <LabelWrapper
              id="vlm-prompt"
              label="Prompt"
              helperText="Sent to the VLM for every page"
            >
              <Textarea
                id="vlm-prompt"
                rows={3}
                value={vlmPrompt}
                onChange={(e) => setVlmPrompt(e.target.value)}
              />
            </LabelWrapper>
          </div>

          <div className="space-y-2">
            <LabelWrapper
              id="vlm-response-format"
              label="Response format"
              helperText="Per-page VLM output. Markdown is compatible with the existing pipeline; the final document is always Docling JSON."
            >
              <Select
                value={vlmResponseFormat}
                onValueChange={setVlmResponseFormat}
              >
                <SelectTrigger id="vlm-response-format">
                  <SelectValue placeholder="Select a format" />
                </SelectTrigger>
                <SelectContent>
                  {RESPONSE_FORMATS.map((format) => (
                    <SelectItem key={format.value} value={format.value}>
                      {format.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </LabelWrapper>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <NumberInput
              id="vlm-max-tokens"
              label="Max tokens per page"
              value={vlmMaxTokens}
              onChange={(value) => setVlmMaxTokens(Math.max(1, value))}
              unit="tokens"
              min={1}
            />
            <NumberInput
              id="vlm-concurrency"
              label="Concurrency"
              value={vlmConcurrency}
              onChange={(value) => setVlmConcurrency(Math.max(1, value))}
              unit="requests"
              min={1}
            />
            <NumberInput
              id="vlm-timeout"
              label="API timeout"
              value={vlmTimeout}
              onChange={(value) => setVlmTimeout(Math.max(1, value))}
              unit="seconds"
              min={1}
            />
          </div>

          {validationError && (
            <p className="text-sm text-destructive" role="alert">
              {validationError}
            </p>
          )}

          <div className="flex justify-end pt-2">
            <Button
              onClick={handleSave}
              disabled={
                updateSettingsMutation.isPending || !vlmDirty || providerWarning
              }
              className="min-w-[120px]"
              size="sm"
              variant="outline"
            >
              {updateSettingsMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Saving...
                </>
              ) : (
                "Save VLM settings"
              )}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
