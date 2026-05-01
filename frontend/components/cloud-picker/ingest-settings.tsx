"use client";

import { ChevronRight } from "lucide-react";
import { useMemo } from "react";
import {
  useGetIBMModelsQuery,
  useGetOllamaModelsQuery,
  useGetOpenAIModelsQuery,
} from "@/app/api/queries/useGetModelsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import type { ModelOption } from "@/app/onboarding/_components/model-selector";
import {
  getFallbackModels,
  type ModelProvider,
} from "@/app/settings/_helpers/model-helpers";
import { ModelSelectItems } from "@/app/settings/_helpers/model-select-item";
import { LabelWrapper } from "@/components/label-wrapper";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { NumberInput } from "@/components/ui/inputs/number-input";
import {
  Select,
  SelectContent,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useAuth } from "@/contexts/auth-context";
import { knowledgeToIngestSettings } from "@/lib/ingest-settings-knowledge";
import type { IngestSettings as IngestSettingsType } from "./types";

interface IngestSettingsProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  settings?: IngestSettingsType;
  onSettingsChange?: (settings: IngestSettingsType) => void;
}

export const IngestSettings = ({
  isOpen,
  onOpenChange,
  settings,
  onSettingsChange,
}: IngestSettingsProps) => {
  const { isAuthenticated, isNoAuthMode } = useAuth();

  // Fetch settings from API to get current embedding model
  const { data: apiSettings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  // Get the current provider from API settings
  const currentProvider = (apiSettings.knowledge?.embedding_provider ||
    "openai") as ModelProvider;

  // Fetch available models based on provider
  const { data: openaiModelsData } = useGetOpenAIModelsQuery(undefined, {
    enabled: (isAuthenticated || isNoAuthMode) && currentProvider === "openai",
  });

  const { data: ollamaModelsData } = useGetOllamaModelsQuery(undefined, {
    enabled: (isAuthenticated || isNoAuthMode) && currentProvider === "ollama",
  });

  const { data: ibmModelsData } = useGetIBMModelsQuery(undefined, {
    enabled: (isAuthenticated || isNoAuthMode) && currentProvider === "watsonx",
  });

  // Select the appropriate models data based on provider
  const modelsData =
    currentProvider === "openai"
      ? openaiModelsData
      : currentProvider === "ollama"
        ? ollamaModelsData
        : currentProvider === "watsonx"
          ? ibmModelsData
          : openaiModelsData;

  const defaultEmbedding = modelsData?.embedding_models?.find(
    (m) => m.default,
  )?.value;

  const defaultSettings: IngestSettingsType = {
    ...knowledgeToIngestSettings(apiSettings.knowledge),
    embeddingModel:
      apiSettings.knowledge?.embedding_model?.trim() ||
      defaultEmbedding ||
      "text-embedding-3-small",
  };

  const currentSettings = settings ?? defaultSettings;

  /** Radix Select only shows a value that exists in <SelectItem>; always include the current model. */
  const embeddingSelectOptions = useMemo(() => {
    const fallbackList = (getFallbackModels(currentProvider).embedding ??
      []) as ModelOption[];
    const fromApi = modelsData?.embedding_models;
    let base: ModelOption[] =
      fromApi && fromApi.length > 0 ? [...fromApi] : [...fallbackList];
    const v = currentSettings.embeddingModel?.trim();
    if (!v) {
      return base.length > 0
        ? base
        : [
            {
              value: "text-embedding-3-small",
              label: "text-embedding-3-small",
            },
          ];
    }
    if (!base.some((m) => m.value === v)) {
      base = [{ value: v, label: v }, ...base];
    }
    return base;
  }, [
    currentProvider,
    modelsData?.embedding_models,
    currentSettings.embeddingModel,
  ]);

  const selectEmbeddingValue =
    embeddingSelectOptions.some(
      (m) => m.value === currentSettings.embeddingModel,
    ) && currentSettings.embeddingModel
      ? currentSettings.embeddingModel
      : (embeddingSelectOptions[0]?.value ?? "text-embedding-3-small");

  const handleSettingsChange = (newSettings: Partial<IngestSettingsType>) => {
    onSettingsChange?.({ ...currentSettings, ...newSettings });
  };

  return (
    <Collapsible
      open={isOpen}
      onOpenChange={onOpenChange}
      className="border rounded-xl p-4 border-border"
    >
      <CollapsibleTrigger className="flex items-center gap-2 justify-between w-full -m-4 p-4 rounded-md transition-colors">
        <div className="flex items-center gap-2">
          <ChevronRight
            className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${
              isOpen ? "rotate-90" : ""
            }`}
          />
          <span className="text-sm font-medium">Ingest settings</span>
        </div>
      </CollapsibleTrigger>

      <CollapsibleContent className="data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:slide-up-2 data-[state=open]:slide-down-2">
        <div className="mt-6">
          {/* Embedding model selection */}
          <LabelWrapper
            helperText="Model used for knowledge ingest and retrieval"
            id="embedding-model-select"
            label="Embedding model"
          >
            <Select
              disabled={false}
              value={selectEmbeddingValue}
              onValueChange={(value) =>
                handleSettingsChange({ embeddingModel: value })
              }
            >
              <Tooltip>
                <TooltipTrigger asChild>
                  <SelectTrigger id="embedding-model-select">
                    <SelectValue placeholder="Select an embedding model" />
                  </SelectTrigger>
                </TooltipTrigger>
                <TooltipContent>
                  Choose the embedding model for this upload
                </TooltipContent>
              </Tooltip>
              <SelectContent>
                <ModelSelectItems
                  models={embeddingSelectOptions}
                  fallbackModels={[]}
                  provider={currentProvider}
                />
              </SelectContent>
            </Select>
          </LabelWrapper>
        </div>
        <div className="mt-6">
          <div className="flex items-center gap-4 w-full mb-6">
            <div className="w-full">
              <NumberInput
                id="chunk-size"
                label="Chunk size"
                value={currentSettings.chunkSize}
                onChange={(value) => handleSettingsChange({ chunkSize: value })}
                unit="characters"
              />
            </div>
            <div className="w-full">
              <NumberInput
                id="chunk-overlap"
                label="Chunk overlap"
                value={currentSettings.chunkOverlap}
                onChange={(value) =>
                  handleSettingsChange({ chunkOverlap: value })
                }
                unit="characters"
              />
            </div>
          </div>

          {/* <div className="flex gap-2 items-center justify-between">
            <div>
              <div className="text-sm font-semibold pb-2">Table Structure</div>
              <div className="text-sm text-muted-foreground">
                Capture table structure during ingest.
              </div>
            </div>
            <Switch
              id="table-structure"
              checked={currentSettings.tableStructure}
              onCheckedChange={(checked) =>
                handleSettingsChange({ tableStructure: checked })
              }
            />
          </div> */}

          <div className="flex items-center justify-between border-b pb-3 mb-3">
            <div>
              <div className="text-sm font-semibold pb-2">OCR</div>
              <div className="text-sm text-muted-foreground">
                Extracts text from images/PDFs. Ingest is slower when enabled.
              </div>
            </div>
            <Switch
              checked={currentSettings.ocr}
              onCheckedChange={(checked) =>
                handleSettingsChange({ ocr: checked })
              }
            />
          </div>

          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm pb-2 font-semibold">
                Picture descriptions
              </div>
              <div className="text-sm text-muted-foreground">
                Adds captions for images. Ingest is more expensive when enabled.
              </div>
            </div>
            <Switch
              checked={currentSettings.pictureDescriptions}
              onCheckedChange={(checked) =>
                handleSettingsChange({ pictureDescriptions: checked })
              }
            />
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
};
