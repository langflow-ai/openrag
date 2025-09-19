"use client";

import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ChevronRight, Info } from "lucide-react";
import { IngestSettings as IngestSettingsType } from "./types";

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
        <div className="pt-5 space-y-5">
          <div className="flex items-center gap-4 w-full">
            <div className="w-full">
              <div className="text-sm mb-2 font-semibold">Chunk size</div>
              <Input
                type="number"
                value={currentSettings.chunkSize}
                onChange={e =>
                  handleSettingsChange({
                    chunkSize: parseInt(e.target.value) || 0,
                  })
                }
              />
            </div>
            <div className="w-full">
              <div className="text-sm mb-2 font-semibold">Chunk overlap</div>
              <Input
                type="number"
                value={currentSettings.chunkOverlap}
                onChange={e =>
                  handleSettingsChange({
                    chunkOverlap: parseInt(e.target.value) || 0,
                  })
                }
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
              onCheckedChange={checked =>
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
              onCheckedChange={checked =>
                handleSettingsChange({ pictureDescriptions: checked })
              }
            />
          </div>

          <div>
            <div className="text-sm font-semibold pb-2 flex items-center">
              Embedding model
              <Info className="w-3.5 h-3.5 text-muted-foreground ml-2" />
            </div>
            <Input
              disabled
              value={currentSettings.embeddingModel}
              onChange={e =>
                handleSettingsChange({ embeddingModel: e.target.value })
              }
              placeholder="text-embedding-3-small"
            />
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
};
