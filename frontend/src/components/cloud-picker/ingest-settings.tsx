"use client";

import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
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
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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
    tableStructure: false,
  };

  // Use provided settings or defaults
  const currentSettings = settings || defaultSettings;

  const handleSettingsChange = (newSettings: Partial<IngestSettingsType>) => {
    const updatedSettings = { ...currentSettings, ...newSettings };
    onSettingsChange?.(updatedSettings);
  };

  return (
    <Collapsible
      open={isOpen}
      onOpenChange={onOpenChange}
      className="border rounded-md p-4 border-muted-foreground/20"
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
        <div className="pt-5 space-y-6">
          <div className="space-y-2">
            <LabelWrapper
              helperText="Model used for knowledge ingest and retrieval"
              id="embedding-model-select"
              label="Embedding model"
            >
              <Select
                disabled={true}
                value={currentSettings.embeddingModel}
                onValueChange={value =>
                  handleSettingsChange({ embeddingModel: value })
                }
              >
                <SelectTrigger disabled id="embedding-model-select">
                  <SelectValue placeholder="text-embedding-3-small" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={currentSettings.embeddingModel}>
                    {currentSettings.embeddingModel}
                  </SelectItem>
                </SelectContent>
              </Select>
            </LabelWrapper>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="chunk-size" className="text-sm font-medium">
                Chunk size
              </Label>
              <div className="relative">
                <Input
                  id="chunk-size"
                  type="number"
                  min="1"
                  value={currentSettings.chunkSize}
                  onChange={e =>
                    handleSettingsChange({
                      chunkSize: Math.max(0, parseInt(e.target.value) || 0),
                    })
                  }
                  className="w-full pr-24"
                />
                <div className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none">
                  <span className="text-sm text-muted-foreground">
                    characters
                  </span>
                </div>
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="chunk-overlap" className="text-sm font-medium">
                Chunk overlap
              </Label>
              <div className="relative">
                <Input
                  id="chunk-overlap"
                  type="number"
                  min="0"
                  value={currentSettings.chunkOverlap}
                  onChange={e =>
                    handleSettingsChange({
                      chunkOverlap: Math.max(0, parseInt(e.target.value) || 0),
                    })
                  }
                  className="w-full pr-24"
                />
                <div className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none">
                  <span className="text-sm text-muted-foreground">
                    characters
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="space-y-6">
            <div className="flex items-center space-x-3">
              <div className="flex-1">
                <Label
                  htmlFor="ocr-toggle"
                  className="text-base font-medium cursor-pointer text-sm"
                >
                  Table Structure
                </Label>
                <div className="text-sm text-muted-foreground">
                  Capture table structure during ingest.
                </div>
              </div>
              <Switch
                id="ocr-toggle"
                checked={currentSettings.tableStructure}
                onCheckedChange={checked =>
                  handleSettingsChange({ tableStructure: checked })
                }
              />
            </div>
            <div className="flex items-center space-x-3">
              <div className="flex-1">
                <Label
                  htmlFor="ocr-toggle"
                  className="text-base font-medium cursor-pointer text-sm"
                >
                  OCR
                </Label>
                <div className="text-sm text-muted-foreground">
                  Extracts text from images and scanned pages.
                </div>
              </div>
              <Switch
                id="ocr-toggle"
                checked={currentSettings.ocr}
                onCheckedChange={checked =>
                  handleSettingsChange({ ocr: checked })
                }
              />
            </div>
            <div className="flex items-center space-x-3">
              <div className="flex-1">
                <Label
                  htmlFor="picture-descriptions-toggle"
                  className="text-base font-medium cursor-pointer text-sm"
                >
                  Picture descriptions
                </Label>
                <div className="text-sm text-muted-foreground">
                  Generates short image captions. More expensive when enabled.
                </div>
              </div>
              <Switch
                id="picture-descriptions-toggle"
                checked={currentSettings.pictureDescriptions}
                onCheckedChange={checked =>
                  handleSettingsChange({ pictureDescriptions: checked })
                }
              />
            </div>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
};
