"use client";

import { ArrowUpRight, Loader2, Minus, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  useGetIBMModelsQuery,
  useGetOllamaModelsQuery,
  useGetOpenAIModelsQuery,
} from "@/app/api/queries/useGetModelsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { LabelWrapper } from "@/components/label-wrapper";
import { RequirePermission } from "@/components/require-permission";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { DEFAULT_KNOWLEDGE_SETTINGS } from "@/lib/constants";
import { deriveCloudLangflowUrl } from "@/lib/url-utils";
import { cn } from "@/lib/utils";
import { useUpdateSettingsMutation } from "../../api/mutations/useUpdateSettingsMutation";
import { ModelSelector } from "../../onboarding/_components/model-selector";
import { getModelLogo } from "../_helpers/model-helpers";
import { LangflowIcon } from "./langflow-icon";

export function IngestSettingsSection() {
  const isCloudBrand = useIsCloudBrand();
  const { isAuthenticated, isNoAuthMode, isIbmAuthMode } = useAuth();

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

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const { data: openaiModels, isLoading: openaiLoading } =
    useGetOpenAIModelsQuery(
      { apiKey: "" },
      { enabled: settings?.providers?.openai?.configured === true },
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

  const groupedEmbeddingModels = [
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
    }));

  const isLoadingAnyEmbeddingModels =
    openaiLoading || ollamaLoading || watsonxLoading;

  const updateSettingsMutation = useUpdateSettingsMutation({
    onSuccess: () => {
      toast.success("Settings updated successfully");
    },
    onError: (error) => {
      toast.error("Failed to update settings", { description: error.message });
    },
  });

  useEffect(() => {
    if (settings.knowledge?.chunk_size !== undefined)
      setChunkSize(settings.knowledge.chunk_size);
  }, [settings.knowledge?.chunk_size]);

  useEffect(() => {
    if (settings.knowledge?.chunk_overlap !== undefined)
      setChunkOverlap(settings.knowledge.chunk_overlap);
  }, [settings.knowledge?.chunk_overlap]);

  useEffect(() => {
    if (settings.knowledge?.table_structure !== undefined)
      setTableStructure(settings.knowledge.table_structure);
  }, [settings.knowledge?.table_structure]);

  useEffect(() => {
    if (settings.knowledge?.ocr !== undefined) setOcr(settings.knowledge.ocr);
  }, [settings.knowledge?.ocr]);

  useEffect(() => {
    if (settings.knowledge?.picture_descriptions !== undefined)
      setPictureDescriptions(settings.knowledge.picture_descriptions);
  }, [settings.knowledge?.picture_descriptions]);

  useEffect(() => {
    if (settings.knowledge?.disable_ingest_with_langflow !== undefined)
      setDisableIngestWithLangflow(
        settings.knowledge.disable_ingest_with_langflow,
      );
  }, [settings.knowledge?.disable_ingest_with_langflow]);

  const k = settings.knowledge;
  const knowledgeIngestDirty =
    chunkSize !== (k?.chunk_size ?? chunkSize) ||
    chunkOverlap !== (k?.chunk_overlap ?? chunkOverlap) ||
    tableStructure !== (k?.table_structure ?? tableStructure) ||
    ocr !== (k?.ocr ?? ocr) ||
    pictureDescriptions !== (k?.picture_descriptions ?? pictureDescriptions) ||
    disableIngestWithLangflow !==
      (k?.disable_ingest_with_langflow ?? disableIngestWithLangflow);

  const handleEmbeddingModelChange = (newModel: string, provider?: string) => {
    if (newModel && provider) {
      updateSettingsMutation.mutate({
        embedding_model: newModel,
        embedding_provider: provider,
      });
    } else if (newModel) {
      updateSettingsMutation.mutate({ embedding_model: newModel });
    }
  };

  const handleChunkSizeChange = (value: string) => {
    setChunkSize(Math.max(0, Number.parseInt(value, 10) || 0));
    setChunkValidationError(null);
  };

  const handleChunkOverlapChange = (value: string) => {
    setChunkOverlap(Math.max(0, Number.parseInt(value, 10) || 0));
    setChunkValidationError(null);
  };

  const handleKnowledgeIngestSave = () => {
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
    updateSettingsMutation.mutate(
      {
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
        table_structure: tableStructure,
        ocr,
        picture_descriptions: pictureDescriptions,
        disable_ingest_with_langflow: disableIngestWithLangflow,
      },
      { onSuccess: () => setChunkValidationError(null) },
    );
  };

  const handleEditInLangflow = (closeDialog: () => void) => {
    const cloudLangflowUrl =
      isIbmAuthMode && typeof window !== "undefined"
        ? deriveCloudLangflowUrl(window.location.origin)
        : null;
    const derivedFromWindow =
      typeof window !== "undefined"
        ? `${window.location.protocol}//${window.location.hostname}:7860`
        : "";
    const base = (
      cloudLangflowUrl ||
      settings.langflow_public_url ||
      derivedFromWindow ||
      "http://localhost:7860"
    ).replace(/\/$/, "");
    const computed = settings.ingest_flow_id
      ? `${base}/flow/${settings.ingest_flow_id}`
      : base;
    window.open(
      settings.langflow_ingest_edit_url || computed,
      "_blank",
      "noopener,noreferrer",
    );
    closeDialog();
  };

  const handleRestoreIngestFlow = (closeDialog: () => void) => {
    fetch("/api/reset-flow/ingest", { method: "POST" })
      .then((res) => {
        if (res.ok) return res.json();
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      })
      .then(() => {
        setChunkSize(DEFAULT_KNOWLEDGE_SETTINGS.chunk_size);
        setChunkOverlap(DEFAULT_KNOWLEDGE_SETTINGS.chunk_overlap);
        setTableStructure(DEFAULT_KNOWLEDGE_SETTINGS.table_structure);
        setOcr(DEFAULT_KNOWLEDGE_SETTINGS.ocr);
        setPictureDescriptions(DEFAULT_KNOWLEDGE_SETTINGS.picture_descriptions);
        setDisableIngestWithLangflow(false);
        setChunkValidationError(null);
        closeDialog();
      })
      .catch((err) => {
        console.error("Error restoring ingest flow:", err);
        closeDialog();
      });
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
          </div>
          <div className="flex justify-end pt-2">
            <Button
              onClick={handleKnowledgeIngestSave}
              disabled={
                updateSettingsMutation.isPending || !knowledgeIngestDirty
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
