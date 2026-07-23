"use client";

import { ArrowUpRight, Loader2, Minus, Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  useGetAnthropicModelsQuery,
  useGetIBMModelsQuery,
  useGetOllamaModelsQuery,
  useGetOpenAIModelsQuery,
} from "@/app/api/queries/useGetModelsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { LabelWrapper } from "@/components/label-wrapper";
import { RequirePermission } from "@/components/require-permission";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
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
import { trackButton } from "@/lib/analytics";
import { DEFAULT_KNOWLEDGE_SETTINGS } from "@/lib/constants";
import { resolveLangflowEditUrl } from "@/lib/url-utils";
import { cn } from "@/lib/utils";
import { useUpdateSettingsMutation } from "../../api/mutations/useUpdateSettingsMutation";
import { ModelSelector } from "../../onboarding/_components/model-selector";
import { getModelLogo } from "../_helpers/model-helpers";
import { LangflowIcon } from "./langflow-icon";

const DEFAULT_WATSONX_API_VERSION = "2023-05-29";

const RESPONSE_FORMATS = [
  { value: "markdown", label: "Markdown (recommended)" },
  { value: "doctags", label: "DocTags" },
  { value: "html", label: "HTML" },
] as const;

export function IngestSettingsSection() {
  const isCloudBrand = useIsCloudBrand();
  const { isAuthenticated, isNoAuthMode, isIbmAuthMode, runMode } = useAuth();

  const [isRestoringFlow, setIsRestoringFlow] = useState<boolean>(false);

  const [chunkSize, setChunkSize] = useState<number>(1024);
  const [chunkOverlap, setChunkOverlap] = useState<number>(50);
  const [chunkValidationError, setChunkValidationError] = useState<
    string | null
  >(null);
  const [tableStructure, setTableStructure] = useState<boolean>(true);
  const [ocr, setOcr] = useState<boolean>(false);
  const [pictureDescriptions, setPictureDescriptions] =
    useState<boolean>(false);
  const [disableIngestWithLangflow, setDisableIngestWithLangflow] =
    useState<boolean>(false);

  const [vlmProvider, setVlmProvider] = useState<string>("openai");
  const [vlmModel, setVlmModel] = useState<string>("");
  const [vlmPrompt, setVlmPrompt] = useState<string>("");
  const [vlmResponseFormat, setVlmResponseFormat] =
    useState<string>("markdown");
  const [vlmMaxTokens, setVlmMaxTokens] = useState<number>(5000);
  const [vlmConcurrency, setVlmConcurrency] = useState<number>(4);
  const [vlmTimeout, setVlmTimeout] = useState<number>(120);
  const [vlmWatsonxApiVersion, setVlmWatsonxApiVersion] = useState<string>(
    DEFAULT_WATSONX_API_VERSION,
  );
  const [validationError, setValidationError] = useState<string | null>(null);

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const showVlmSettings = settings.show_vlm_settings ?? true;

  const { data: openaiModels, isLoading: openaiLoading } =
    useGetOpenAIModelsQuery(
      { apiKey: "" },
      { enabled: settings?.providers?.openai?.configured === true },
    );
  const { data: anthropicModels, isLoading: anthropicLoading } =
    useGetAnthropicModelsQuery(
      { apiKey: "" },
      { enabled: settings?.providers?.anthropic?.configured === true },
    );
  const { data: ollamaModels, isLoading: ollamaLoading } =
    useGetOllamaModelsQuery(
      { endpoint: settings?.providers?.ollama?.endpoint },
      {
        enabled:
          settings?.providers?.ollama?.configured === true &&
          !!settings?.providers?.ollama?.endpoint,
      },
    );
  const { data: watsonxModels, isLoading: watsonxLoading } =
    useGetIBMModelsQuery(
      {
        endpoint: settings?.providers?.watsonx?.endpoint,
        apiKey: "",
        projectId: settings?.providers?.watsonx?.project_id,
      },
      {
        enabled:
          settings?.providers?.watsonx?.configured === true &&
          !!settings?.providers?.watsonx?.endpoint &&
          !!settings?.providers?.watsonx?.project_id,
      },
    );

  const groupedEmbeddingModels = useMemo(
    () =>
      [
        {
          group: "OpenAI",
          provider: "openai",
          icon: getModelLogo("", "openai"),
          models: openaiModels?.embedding_models || [],
          configured: settings.providers?.openai?.configured === true,
        },
        {
          group: "Ollama",
          provider: "ollama",
          icon: getModelLogo("", "ollama"),
          models: ollamaModels?.embedding_models || [],
          configured: settings.providers?.ollama?.configured === true,
        },
        {
          group: "IBM watsonx.ai",
          provider: "watsonx",
          icon: getModelLogo("", "watsonx"),
          models: watsonxModels?.embedding_models || [],
          configured: settings.providers?.watsonx?.configured === true,
        },
      ]
        .filter((p) => p.configured)
        .map((p) => ({
          group: p.group,
          icon: p.icon,
          options: p.models.map((m) => ({ ...m, provider: p.provider })),
        })),
    [
      openaiModels?.embedding_models,
      ollamaModels?.embedding_models,
      watsonxModels?.embedding_models,
      settings.providers?.openai?.configured,
      settings.providers?.ollama?.configured,
      settings.providers?.watsonx?.configured,
    ],
  );

  const isLoadingAnyEmbeddingModels =
    openaiLoading || ollamaLoading || watsonxLoading;

  const groupedVlmModels = useMemo(() => {
    const list: any[] = [];

    // 1. Local Models
    if (settings.local_vlm_models && settings.local_vlm_models.length > 0) {
      list.push({
        group: "Local Models",
        icon: getModelLogo("", "local"),
        options: settings.local_vlm_models.map((m: string) => ({
          value: m,
          label: m.split("/").pop(),
          provider: "local",
        })),
      });
    }

    // 2. OpenAI
    if (settings.providers?.openai?.configured) {
      const models = (openaiModels?.language_models || [])
        .filter((m: any) => m.supports_images === true)
        .map((m: any) => ({ ...m, provider: "openai" }));
      if (models.length > 0) {
        list.push({
          group: "OpenAI",
          icon: getModelLogo("", "openai"),
          options: models,
        });
      }
    }

    // 3. Anthropic
    if (settings.providers?.anthropic?.configured) {
      const models = (anthropicModels?.language_models || [])
        .filter((m: any) => m.supports_images === true)
        .map((m: any) => ({ ...m, provider: "anthropic" }));
      if (models.length > 0) {
        list.push({
          group: "Anthropic",
          icon: getModelLogo("", "anthropic"),
          options: models,
        });
      }
    }

    // 4. Ollama
    if (settings.providers?.ollama?.configured) {
      const models = (ollamaModels?.language_models || [])
        .filter((m: any) => m.supports_images === true)
        .map((m: any) => ({ ...m, provider: "ollama" }));
      if (models.length > 0) {
        list.push({
          group: "Ollama",
          icon: getModelLogo("", "ollama"),
          options: models,
        });
      }
    }

    // 5. IBM watsonx.ai
    if (settings.providers?.watsonx?.configured) {
      const models = (watsonxModels?.language_models || [])
        .filter((m: any) => m.supports_images === true)
        .map((m: any) => ({ ...m, provider: "watsonx" }));
      if (models.length > 0) {
        list.push({
          group: "IBM watsonx.ai",
          icon: getModelLogo("", "watsonx"),
          options: models,
        });
      }
    }

    return list;
  }, [
    settings.local_vlm_models,
    settings.providers?.openai?.configured,
    settings.providers?.anthropic?.configured,
    settings.providers?.ollama?.configured,
    settings.providers?.watsonx?.configured,
    openaiModels?.language_models,
    anthropicModels?.language_models,
    ollamaModels?.language_models,
    watsonxModels?.language_models,
  ]);

  const isLoadingAnyVlmModels =
    openaiLoading || anthropicLoading || ollamaLoading || watsonxLoading;

  const allVlmOptions = useMemo(
    () => groupedVlmModels.flatMap((g) => g.options),
    [groupedVlmModels],
  );

  const updateSettingsMutation = useUpdateSettingsMutation({
    onSuccess: () => {
      toast.success("Settings updated successfully");
    },
    onError: (error) => {
      toast.error("Failed to update settings", { description: error.message });
    },
  });

  const allEmbeddingOptions = useMemo(
    () => groupedEmbeddingModels.flatMap((g) => g.options),
    [groupedEmbeddingModels],
  );

  const handleEmbeddingModelChange = useCallback(
    (newModel: string, provider?: string) => {
      if (newModel && provider) {
        updateSettingsMutation.mutate({
          embedding_model: newModel,
          embedding_provider: provider,
        });
      } else if (newModel) {
        updateSettingsMutation.mutate({ embedding_model: newModel });
      }
    },
    [updateSettingsMutation],
  );

  const autoSelectedEmbedding = useRef(false);
  useEffect(() => {
    if (settings.knowledge?.embedding_model) {
      autoSelectedEmbedding.current = false;
      return;
    }
    if (autoSelectedEmbedding.current) return;
    if (allEmbeddingOptions.length > 0) {
      autoSelectedEmbedding.current = true;
      const fallback =
        allEmbeddingOptions.find((o) => o.default) || allEmbeddingOptions[0];
      handleEmbeddingModelChange(fallback.value, fallback.provider);
    }
  }, [
    settings.knowledge?.embedding_model,
    allEmbeddingOptions,
    handleEmbeddingModelChange,
  ]);

  useEffect(() => {
    const k = settings.knowledge;
    if (!k) return;
    if (k.chunk_size !== undefined) setChunkSize(k.chunk_size);
    if (k.chunk_overlap !== undefined) setChunkOverlap(k.chunk_overlap);
    if (k.table_structure !== undefined) setTableStructure(k.table_structure);
    if (k.ocr !== undefined) setOcr(k.ocr);
    if (k.picture_descriptions !== undefined)
      setPictureDescriptions(k.picture_descriptions);
    if (k.disable_ingest_with_langflow !== undefined)
      setDisableIngestWithLangflow(k.disable_ingest_with_langflow);
    if (k.vlm_provider !== undefined) setVlmProvider(k.vlm_provider);
    // Backend defaults vlm_model to ""; an empty value means "not configured",
    // so don't clobber a locally auto-selected model with it.
    if (k.vlm_model) setVlmModel(k.vlm_model);
    if (k.vlm_prompt !== undefined) setVlmPrompt(k.vlm_prompt);
    if (k.vlm_response_format !== undefined)
      setVlmResponseFormat(k.vlm_response_format);
    if (k.vlm_max_tokens !== undefined) setVlmMaxTokens(k.vlm_max_tokens);
    if (k.vlm_concurrency !== undefined) setVlmConcurrency(k.vlm_concurrency);
    if (k.vlm_timeout !== undefined) setVlmTimeout(k.vlm_timeout);
    if (k.vlm_watsonx_api_version !== undefined)
      setVlmWatsonxApiVersion(k.vlm_watsonx_api_version);
  }, [settings.knowledge]);

  const [vlmAccordionValue, setVlmAccordionValue] = useState<string>("");

  const autoSelectedVlm = useRef(false);
  useEffect(() => {
    if (!showVlmSettings) return;
    if (settings.knowledge?.vlm_model) {
      autoSelectedVlm.current = false;
      return;
    }
    if (autoSelectedVlm.current) return;
    if (settings.local_vlm_models && settings.local_vlm_models.length > 0) {
      setVlmModel(settings.local_vlm_models[0]);
      setVlmProvider("local");
      autoSelectedVlm.current = true;
    } else if (allVlmOptions.length > 0) {
      const fallback = allVlmOptions.find((o) => o.default) || allVlmOptions[0];
      setVlmModel(fallback.value);
      setVlmProvider(fallback.provider || "openai");
      autoSelectedVlm.current = true;
    }
  }, [
    showVlmSettings,
    settings.knowledge?.vlm_model,
    settings.local_vlm_models,
    allVlmOptions,
  ]);

  const handleVlmModelChange = (value: string, provider?: string) => {
    setVlmModel(value);
    if (provider) setVlmProvider(provider);
    setValidationError(null);
  };

  const vlmModelPending =
    showVlmSettings && pictureDescriptions && !vlmModel.trim();

  const k = settings.knowledge;
  const vlmDirty =
    showVlmSettings &&
    (pictureDescriptions !== (k?.vlm_enabled ?? pictureDescriptions) ||
      vlmProvider !== (k?.vlm_provider ?? vlmProvider) ||
      vlmModel !== (k?.vlm_model ?? vlmModel) ||
      vlmPrompt !== (k?.vlm_prompt ?? vlmPrompt) ||
      vlmResponseFormat !== (k?.vlm_response_format ?? vlmResponseFormat) ||
      vlmMaxTokens !== (k?.vlm_max_tokens ?? vlmMaxTokens) ||
      vlmConcurrency !== (k?.vlm_concurrency ?? vlmConcurrency) ||
      vlmTimeout !== (k?.vlm_timeout ?? vlmTimeout) ||
      vlmWatsonxApiVersion !==
        (k?.vlm_watsonx_api_version ?? vlmWatsonxApiVersion));

  const knowledgeIngestDirty =
    chunkSize !== (k?.chunk_size ?? chunkSize) ||
    chunkOverlap !== (k?.chunk_overlap ?? chunkOverlap) ||
    tableStructure !== (k?.table_structure ?? tableStructure) ||
    ocr !== (k?.ocr ?? ocr) ||
    pictureDescriptions !== (k?.picture_descriptions ?? pictureDescriptions) ||
    disableIngestWithLangflow !==
      (k?.disable_ingest_with_langflow ?? disableIngestWithLangflow) ||
    vlmDirty;

  const providerConfigured =
    settings.providers === undefined || settings.providers === null
      ? undefined
      : vlmProvider === "watsonx"
        ? settings.providers.watsonx?.configured === true
        : vlmProvider === "anthropic"
          ? settings.providers.anthropic?.configured === true
          : vlmProvider === "ollama"
            ? settings.providers.ollama?.configured === true
            : vlmProvider === "local"
              ? true
              : settings.providers.openai?.configured === true;

  const providerWarning = pictureDescriptions && providerConfigured === false;
  const providerLabel =
    vlmProvider === "watsonx"
      ? "IBM watsonx.ai"
      : vlmProvider === "anthropic"
        ? "Anthropic"
        : vlmProvider === "ollama"
          ? "Ollama"
          : "OpenAI";

  const handleChunkSizeChange = (value: string) => {
    setChunkSize(Math.max(0, Number.parseInt(value, 10) || 0));
    setChunkValidationError(null);
  };

  const handleChunkOverlapChange = (value: string) => {
    setChunkOverlap(Math.max(0, Number.parseInt(value, 10) || 0));
    setChunkValidationError(null);
  };

  const handleKnowledgeIngestSave = () => {
    // Only include VLM fields when the VLM UI is enabled; a hidden section
    // must not drive backend VLM state or trip its validation.
    const vlmPayload = showVlmSettings
      ? {
          vlm_enabled: pictureDescriptions,
          vlm_provider: vlmProvider,
          vlm_model: vlmModel.trim() || undefined,
          vlm_prompt: vlmPrompt,
          vlm_response_format: vlmResponseFormat,
          vlm_max_tokens: vlmMaxTokens,
          vlm_concurrency: vlmConcurrency,
          vlm_timeout: vlmTimeout,
          vlm_watsonx_api_version: vlmWatsonxApiVersion,
        }
      : {};

    trackButton({
      CTA: "Save Ingest Settings",
      elementId: "save-ingest-settings-button",
      namespace: "settings",
      payload: {
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
        table_structure: tableStructure,
        ocr,
        picture_descriptions: pictureDescriptions,
        disable_ingest_with_langflow: disableIngestWithLangflow,
        ...vlmPayload,
      },
    });

    if (chunkSize < 1) {
      const msg = "Chunk size must be at least 1";
      setChunkValidationError(msg);
      toast.error("Could not save ingest settings", { description: msg });
      return;
    }
    if (chunkOverlap >= chunkSize) {
      const msg = "Chunk overlap must be less than chunk size";
      setChunkValidationError(msg);
      toast.error("Could not save ingest settings", { description: msg });
      return;
    }

    if (showVlmSettings && pictureDescriptions) {
      if (!vlmModel.trim()) {
        const msg =
          "Model name is required when picture descriptions are enabled";
        setValidationError(msg);
        toast.error("Could not save ingest settings", { description: msg });
        return;
      }
      if (vlmMaxTokens < 1 || vlmConcurrency < 1 || vlmTimeout < 1) {
        const msg = "Max tokens, concurrency, and timeout must be at least 1";
        setValidationError(msg);
        toast.error("Could not save ingest settings", { description: msg });
        return;
      }
    }

    updateSettingsMutation.mutate(
      {
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
        table_structure: tableStructure,
        ocr,
        picture_descriptions: pictureDescriptions,
        disable_ingest_with_langflow: disableIngestWithLangflow,
        ...vlmPayload,
      },
      {
        onSuccess: () => {
          setChunkValidationError(null);
          setValidationError(null);
        },
      },
    );
  };

  const handleEditInLangflow = (closeDialog: () => void) => {
    trackButton({
      CTA: "Edit in Langflow - Ingest",
      elementId: "edit-langflow-ingest-button",
      namespace: "settings",
    });
    window.open(
      resolveLangflowEditUrl({
        flowId: settings.ingest_flow_id,
        editUrlOverride: settings.langflow_ingest_edit_url,
        publicUrl: settings.langflow_public_url,
        langflowPort: settings.langflow_port,
        isIbmAuthMode,
        runMode,
      }),
      "_blank",
      "noopener,noreferrer",
    );
    closeDialog();
  };

  const handleRestoreIngestFlow = (closeDialog: () => void) => {
    setIsRestoringFlow(true);

    trackButton({
      CTA: "Restore Flow - Ingest",
      elementId: "restore-ingest-flow-button",
      namespace: "settings",
    });
    fetch("/api/reset-flow/ingest", { method: "POST" })
      .then((res) =>
        res.text().then((text) => {
          const body = text ? JSON.parse(text) : {};
          if (!res.ok) {
            throw new Error(
              body.error ?? `HTTP ${res.status}: ${res.statusText}`,
            );
          }
        }),
      )
      .then(() => {
        setChunkSize(DEFAULT_KNOWLEDGE_SETTINGS.chunk_size);
        setChunkOverlap(DEFAULT_KNOWLEDGE_SETTINGS.chunk_overlap);
        setTableStructure(DEFAULT_KNOWLEDGE_SETTINGS.table_structure);
        setOcr(DEFAULT_KNOWLEDGE_SETTINGS.ocr);
        setPictureDescriptions(DEFAULT_KNOWLEDGE_SETTINGS.picture_descriptions);
        setDisableIngestWithLangflow(false);
        setChunkValidationError(null);
        toast.success("Default ingest flow settings restored successfully");
        closeDialog();
      })
      .catch((err) => {
        console.error("Error restoring ingest flow:", err);
        toast.error(
          err.message || "Failed to restore default ingest flow settings",
        );
        closeDialog();
      })
      .finally(() => setIsRestoringFlow(false));
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between mb-3">
          <CardTitle
            className={cn(
              "text-lg",
              isCloudBrand && "ibm-settings-section-title",
            )}
          >
            Knowledge Ingest
          </CardTitle>
          <RequirePermission perm="flows:edit">
            <div className="flex gap-2">
              <ConfirmationDialog
                trigger={
                  <Button ignoreTitleCase={true} variant="outline">
                    Restore flow
                  </Button>
                }
                title="Restore default Ingest flow"
                description="This restores defaults and discards all custom settings and overrides. This can't be undone."
                confirmText="Restore"
                variant="destructive"
                onConfirm={handleRestoreIngestFlow}
                isLoading={isRestoringFlow}
              />
              <ConfirmationDialog
                trigger={
                  <Button>
                    <LangflowIcon />
                    Edit in Langflow
                  </Button>
                }
                title="Edit Ingest flow in Langflow"
                description={
                  <>
                    <p className="mb-2">
                      You&apos;re entering Langflow. You can edit the{" "}
                      <b>Ingest flow</b> and other underlying flows. Manual
                      changes to components, wiring, or I/O can break this
                      experience.
                    </p>
                    <p className="mb-2">
                      To enable editing, you need to unlock the flow by clicking
                      on its name and disabling the <b>Lock flow</b> option.
                    </p>
                    <p>You can restore this flow from Settings.</p>
                  </>
                }
                confirmText="Proceed"
                confirmIcon={<ArrowUpRight />}
                variant="warning"
                onConfirm={handleEditInLangflow}
              />
            </div>
          </RequirePermission>
        </div>
        <CardDescription>
          Configure how files are ingested and stored for retrieval. The
          embedding model saves as soon as you pick one; chunk and ingest
          options use Save ingest settings. Edit in Langflow for full control.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          <div className="space-y-2">
            <LabelWrapper
              helperText="Saves immediately when you select a model"
              id="embedding-model-select"
              label="Embedding model"
              required={true}
            >
              <ModelSelector
                groupedOptions={groupedEmbeddingModels}
                noOptionsPlaceholder={
                  isLoadingAnyEmbeddingModels
                    ? "Loading models..."
                    : "No embedding models detected. Configure a provider first."
                }
                value={settings.knowledge?.embedding_model || ""}
                onValueChange={handleEmbeddingModelChange}
              />
            </LabelWrapper>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <LabelWrapper id="chunk-size" label="Chunk size">
                <div className="relative [&:has(input:hover):not(:has(input:focus))_button]:border-muted-foreground [&:has(input:focus)_button]:border-foreground">
                  <Input
                    id="chunk-size"
                    type="number"
                    min="1"
                    value={chunkSize}
                    onChange={(e) => handleChunkSizeChange(e.target.value)}
                    className={`w-full pr-20 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none${chunkValidationError ? " border-destructive" : ""}`}
                  />
                  <div className="absolute inset-y-0 right-0 flex items-center">
                    <span className="text-sm text-placeholder-foreground mr-4 pointer-events-none">
                      characters
                    </span>
                    <div className="flex flex-col">
                      <Button
                        aria-label="Increase value"
                        className="h-5 rounded-l-none rounded-br-none border-input border-b-[0.5px] focus-visible:relative transition-colors"
                        variant="outline"
                        size="iconSm"
                        onClick={() =>
                          handleChunkSizeChange((chunkSize + 1).toString())
                        }
                      >
                        <Plus className="text-muted-foreground" size={8} />
                      </Button>
                      <Button
                        aria-label="Decrease value"
                        className="h-5 rounded-l-none rounded-tr-none border-input border-t-[0.5px] focus-visible:relative transition-colors"
                        variant="outline"
                        size="iconSm"
                        onClick={() =>
                          handleChunkSizeChange((chunkSize - 1).toString())
                        }
                      >
                        <Minus className="text-muted-foreground" size={8} />
                      </Button>
                    </div>
                  </div>
                </div>
              </LabelWrapper>
            </div>
            <div className="space-y-2">
              <LabelWrapper id="chunk-overlap" label="Chunk overlap">
                <div className="relative [&:has(input:hover):not(:has(input:focus))_button]:border-muted-foreground [&:has(input:focus)_button]:border-foreground">
                  <Input
                    id="chunk-overlap"
                    type="number"
                    min="0"
                    value={chunkOverlap}
                    onChange={(e) => handleChunkOverlapChange(e.target.value)}
                    className={`w-full pr-20 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none${chunkValidationError ? " border-destructive" : ""}`}
                  />
                  <div className="absolute inset-y-0 right-0 flex items-center">
                    <span className="text-sm text-placeholder-foreground mr-4 pointer-events-none">
                      characters
                    </span>
                    <div className="flex flex-col">
                      <Button
                        aria-label="Increase value"
                        className="h-5 rounded-l-none rounded-br-none border-input border-b-[0.5px] focus-visible:relative transition-colors"
                        variant="outline"
                        size="iconSm"
                        onClick={() =>
                          handleChunkOverlapChange(
                            (chunkOverlap + 1).toString(),
                          )
                        }
                      >
                        <Plus className="text-muted-foreground" size={8} />
                      </Button>
                      <Button
                        aria-label="Decrease value"
                        className="h-5 rounded-l-none rounded-tr-none border-input border-t-[0.5px] focus-visible:relative transition-colors"
                        variant="outline"
                        size="iconSm"
                        onClick={() =>
                          handleChunkOverlapChange(
                            (chunkOverlap - 1).toString(),
                          )
                        }
                      >
                        <Minus className="text-muted-foreground" size={8} />
                      </Button>
                    </div>
                  </div>
                </div>
              </LabelWrapper>
              {chunkValidationError && (
                <p className="text-sm text-destructive mt-1" role="alert">
                  {chunkValidationError}
                </p>
              )}
            </div>
          </div>
          <div>
            <div className="flex items-center justify-between py-3 border-b border-border">
              <div className="flex-1">
                <Label
                  htmlFor="disable-ingest-with-langflow"
                  className="text-base font-medium cursor-pointer pb-3"
                >
                  Disable Langflow Ingestion
                </Label>
                <div className="text-sm text-muted-foreground">
                  Bypass Langflow for document ingestion and use traditional
                  processing.
                </div>
              </div>
              <Switch
                id="disable-ingest-with-langflow"
                checked={disableIngestWithLangflow}
                onCheckedChange={setDisableIngestWithLangflow}
              />
            </div>
            <div className="flex items-center justify-between py-3 border-b border-border">
              <div className="flex-1">
                <Label
                  htmlFor="table-structure"
                  className="text-base font-medium cursor-pointer pb-3"
                >
                  Table Structure
                </Label>
                <div className="text-sm text-muted-foreground">
                  Capture table structure during ingest.
                </div>
              </div>
              <Switch
                id="table-structure"
                checked={tableStructure}
                onCheckedChange={setTableStructure}
              />
            </div>
            <div className="flex items-center justify-between py-3 border-b border-border">
              <div className="flex-1">
                <Label
                  htmlFor="ocr"
                  className="text-base font-medium cursor-pointer pb-3"
                >
                  OCR
                </Label>
                <div className="text-sm text-muted-foreground">
                  Extracts text from images/PDFs. Ingest is slower when enabled.
                </div>
              </div>
              <Switch id="ocr" checked={ocr} onCheckedChange={setOcr} />
            </div>
            <div className="flex items-center justify-between py-3">
              <div className="flex-1">
                <Label
                  htmlFor="picture-descriptions"
                  className="text-base font-medium cursor-pointer pb-3"
                >
                  Picture Descriptions
                </Label>
                <div className="text-sm text-muted-foreground">
                  Adds captions for images. Ingest is slower when enabled.
                </div>
              </div>
              <Switch
                id="picture-descriptions"
                checked={pictureDescriptions}
                onCheckedChange={setPictureDescriptions}
              />
            </div>
            {showVlmSettings && (
              <div
                className={cn(
                  "mt-4 border border-border rounded-lg bg-muted/5 overflow-hidden transition-all duration-200",
                  !pictureDescriptions &&
                    "opacity-50 cursor-not-allowed select-none",
                )}
              >
                <Accordion
                  type="single"
                  collapsible
                  disabled={!pictureDescriptions}
                  value={pictureDescriptions ? vlmAccordionValue : ""}
                  onValueChange={setVlmAccordionValue}
                >
                  <AccordionItem value="vlm-settings" className="border-none">
                    <AccordionTrigger
                      className={cn(
                        "hover:no-underline font-medium text-foreground px-4 py-3 bg-muted/10 border-b border-border",
                        !pictureDescriptions && "pointer-events-none",
                      )}
                    >
                      Advanced Vision Model (VLM) Settings
                    </AccordionTrigger>
                    <AccordionContent className="p-4 space-y-6">
                      <div className="space-y-2">
                        <LabelWrapper
                          id="vlm-model"
                          label="Vision model"
                          helperText="Pick a vision-capable model; the provider is set from your selection"
                          required={pictureDescriptions}
                        >
                          <ModelSelector
                            groupedOptions={groupedVlmModels}
                            noOptionsPlaceholder={
                              isLoadingAnyVlmModels
                                ? "Loading models..."
                                : "No models detected. Configure OpenAI, Anthropic, Ollama, or IBM watsonx.ai first."
                            }
                            value={vlmModel}
                            onValueChange={handleVlmModelChange}
                            hasError={!!validationError}
                          />
                        </LabelWrapper>
                        {providerWarning && (
                          <p className="text-sm text-destructive" role="alert">
                            {providerLabel} is not configured. Configure it in
                            Settings &gt; Providers first.
                          </p>
                        )}
                      </div>

                      {vlmProvider === "watsonx" && (
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
                              onChange={(e) =>
                                setVlmWatsonxApiVersion(e.target.value)
                              }
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
                                <SelectItem
                                  key={format.value}
                                  value={format.value}
                                >
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
                          onChange={(value) =>
                            setVlmMaxTokens(Math.max(1, value))
                          }
                          unit="tokens"
                          min={1}
                        />
                        <NumberInput
                          id="vlm-concurrency"
                          label="Concurrency"
                          value={vlmConcurrency}
                          onChange={(value) =>
                            setVlmConcurrency(Math.max(1, value))
                          }
                          unit="requests"
                          min={1}
                        />
                        <NumberInput
                          id="vlm-timeout"
                          label="API timeout"
                          value={vlmTimeout}
                          onChange={(value) =>
                            setVlmTimeout(Math.max(1, value))
                          }
                          unit="seconds"
                          min={1}
                        />
                      </div>

                      {validationError && (
                        <p className="text-sm text-destructive" role="alert">
                          {validationError}
                        </p>
                      )}
                    </AccordionContent>
                  </AccordionItem>
                </Accordion>
              </div>
            )}
          </div>
          <div className="flex justify-end pt-2">
            <Button
              onClick={handleKnowledgeIngestSave}
              disabled={
                updateSettingsMutation.isPending ||
                !knowledgeIngestDirty ||
                vlmModelPending
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
                "Save ingest settings"
              )}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
