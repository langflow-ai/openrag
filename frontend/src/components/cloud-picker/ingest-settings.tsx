"use client";

import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ChevronRight } from "lucide-react";
import { IngestSettings as IngestSettingsType } from "./types";
import { LabelWrapper } from "@/components/label-wrapper";
import {
  Select,
  SelectContent,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ModelSelectItems } from "@/app/settings/helpers/model-select-item";
import { getFallbackModels } from "@/app/settings/helpers/model-helpers";
import { NumberInput } from "@/components/ui/inputs/number-input";

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
  // Default settings
  const defaultSettings: IngestSettingsType = {
    chunkSize: 1000,
    chunkOverlap: 200,
    ocr: false,
    pictureDescriptions: false,
    embeddingModel: "text-embedding-3-small",
  };

  // Use provided settings or defaults
  const currentSettings = settings || defaultSettings;

  const handleSettingsChange = (newSettings: Partial<IngestSettingsType>) => {
    const updatedSettings = { ...currentSettings, ...newSettings };
    onSettingsChange?.(updatedSettings);
  };

  console.log({ currentSettings });

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
          {/* Embedding model selection - currently disabled */}
          <LabelWrapper
            helperText="Model used for knowledge ingest and retrieval"
            id="embedding-model-select"
            label="Embedding model"
          >
            <Select
              // Disabled until API supports multiple embedding models
              disabled={true}
              value={currentSettings.embeddingModel}
              onValueChange={() => {}}
            >
              <Tooltip>
                <TooltipTrigger asChild>
                  <SelectTrigger disabled id="embedding-model-select">
                    <SelectValue placeholder="Select an embedding model" />
                  </SelectTrigger>
                </TooltipTrigger>
                <TooltipContent>
                  Locked to keep embeddings consistent
                </TooltipContent>
              </Tooltip>
              <SelectContent>
                <ModelSelectItems
                  models={[
                    {
                      value: "text-embedding-3-small",
                      label: "text-embedding-3-small",
                    },
                  ]}
                  fallbackModels={getFallbackModels("openai").embedding}
                  provider={"openai"}
                />
              </SelectContent>
            </Select>
          </LabelWrapper>
        </div>
        <div className="pt-5 space-y-5">
          <div className="flex items-center gap-4 w-full">
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

          <div className="flex gap-2 items-center justify-between">
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

          <div className="flex gap-2 items-center justify-between">
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
