"use client";

import { ChevronRight } from "lucide-react";
import { useMemo } from "react";
import { useGetModelCatalogQuery } from "@/app/api/queries/useGetModelsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { LabelWrapper } from "@/components/label-wrapper";
import { groupedCatalogOptions } from "@/components/models/catalog-models";
import {
  getFallbackModels,
  type ModelProvider,
} from "@/components/models/model-helpers";
import { ModelSelectItems } from "@/components/models/model-select-item";
import type { ModelOption } from "@/components/models/model-selector";
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
  /** When true, show the "Make documents available to all users" toggle. COS ingestion only. */
  showShared?: boolean;
  /**
   * When false, hide the embedding model, chunking, OCR, and picture description
   * controls, leaving only the shared toggle (if `showShared` is also true). Lets
   * deployments that disable per-upload ingest tuning (e.g. SaaS) still expose the
   * shared toggle on its own. Defaults to true.
   */
  showAdvancedSettings?: boolean;
}

export const IngestSettings = ({
  isOpen,
  onOpenChange,
  settings,
  onSettingsChange,
  showShared = false,
  showAdvancedSettings = true,
}: IngestSettingsProps) => {
  const { isAuthenticated, isNoAuthMode } = useAuth();

  // Fetch settings from API to get current embedding model
  const { data: apiSettings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  // Get the current provider from API settings
  const currentProvider = (apiSettings.knowledge?.embedding_provider ||
    "openai") as ModelProvider;

  const { data: catalog } = useGetModelCatalogQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  // `groupedCatalogOptions` keys off the provider string, so a generic LiteLLM
  // provider resolves here too; restricting this to the four legacy keys hid
  // the catalogue models of every custom embedding provider. An unknown
  // provider simply yields no group and falls through to `getFallbackModels`.
  const catalogEmbeddingModels = useMemo(
    () =>
      groupedCatalogOptions(
        catalog,
        { [currentProvider]: true },
        "embedding",
      )[0]?.options ?? [],
    [catalog, currentProvider],
  );

  const defaultEmbedding = catalogEmbeddingModels[0]?.value;

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
    let base: ModelOption[] =
      catalogEmbeddingModels.length > 0
        ? [...catalogEmbeddingModels]
        : [...fallbackList];
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
  }, [currentProvider, catalogEmbeddingModels, currentSettings.embeddingModel]);

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
        {showAdvancedSettings && (
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
        )}
        {showAdvancedSettings && (
          <div className="mt-6">
            <div className="flex items-center gap-4 w-full mb-6">
              <div className="w-full">
                <NumberInput
                  id="chunk-size"
                  label="Chunk size"
                  value={currentSettings.chunkSize}
                  onChange={(value) =>
                    handleSettingsChange({ chunkSize: value })
                  }
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

            <div
              className={
                showShared
                  ? "flex items-center justify-between border-b pb-3 mb-3"
                  : "flex items-center justify-between"
              }
            >
              <div>
                <div className="text-sm pb-2 font-semibold">
                  Picture descriptions
                </div>
                <div className="text-sm text-muted-foreground">
                  Adds captions for images. Ingest is more expensive when
                  enabled.
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
        )}

        <div className={showAdvancedSettings ? "" : "mt-6"}>
          {showShared && (
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm pb-2 font-semibold">
                  Make documents available to all users
                </div>
                <div className="text-sm text-muted-foreground">
                  Shared documents are visible to all users in this OpenRAG
                  instance.
                </div>
              </div>
              <Switch
                checked={currentSettings.shared ?? false}
                onCheckedChange={(checked) =>
                  handleSettingsChange({ shared: checked })
                }
              />
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
};
