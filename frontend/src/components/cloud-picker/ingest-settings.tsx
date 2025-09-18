"use client";

import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ChevronRight, Info } from "lucide-react";

interface IngestSettingsProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}

export const IngestSettings = ({
  isOpen,
  onOpenChange,
}: IngestSettingsProps) => (
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
            <Input type="number" />
          </div>
          <div className="w-full">
            <div className="text-sm mb-2 font-semibold">Chunk overlap</div>
            <Input type="number" />
          </div>
        </div>

        <div className="flex gap-2 items-center justify-between">
          <div>
            <div className="text-sm font-semibold pb-2">OCR</div>
            <div className="text-sm text-muted-foreground">
              Extracts text from images/PDFs. Ingest is slower when enabled.
            </div>
          </div>
          <Switch />
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
          <Switch />
        </div>

        <div>
          <div className="text-sm font-semibold pb-2 flex items-center">
            Embedding model
            <Info className="w-3.5 h-3.5 text-muted-foreground ml-2" />
          </div>
          <Input value="text-embedding-3-small" disabled />
        </div>
      </div>
    </CollapsibleContent>
  </Collapsible>
);
