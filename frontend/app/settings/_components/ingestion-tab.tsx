"use client";

import { ChevronDown, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { isIngestPreviewEnabled } from "@/lib/ingest-preview";
import { cn } from "@/lib/utils";
import { IngestPreviewSettingsSection } from "./ingest-preview-settings-section";
import { IngestSaveProvider, useIngestSave } from "./ingest-save-context";
import { IngestSettingsSection } from "./ingest-settings-section";

function IngestSaveBar() {
  const { isDirty, isBlocked, isSaving, saveAll } = useIngestSave();

  return (
    <div className="flex justify-end pt-2">
      <Button
        type="button"
        size="sm"
        className="min-w-[120px]"
        disabled={!isDirty || isBlocked || isSaving}
        data-testid="ingest-save"
        onClick={async () => {
          if (await saveAll()) toast.success("Ingest settings saved");
        }}
      >
        {isSaving ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Saving...
          </>
        ) : (
          "Save changes"
        )}
      </Button>
    </div>
  );
}

export function IngestionTab() {
  const { runMode } = useAuth();
  const isCloudBrand = useIsCloudBrand();
  const showPreview = isIngestPreviewEnabled(runMode, { isCloudBrand });
  const [previewOpen, setPreviewOpen] = useState(true);

  return (
    <IngestSaveProvider>
      <div className="space-y-8">
        <IngestSettingsSection />
        {showPreview ? (
          <Collapsible
            asChild
            open={previewOpen}
            onOpenChange={setPreviewOpen}
            className="border-t border-border pt-8"
          >
            <section>
              <CollapsibleTrigger className="group flex w-full items-start justify-between gap-6 text-left">
                <div className="max-w-[545px] space-y-3">
                  <h3 className="text-lg font-semibold leading-tight tracking-tight">
                    Ingest preview
                  </h3>
                  <p className="text-sm text-muted-foreground">
                    Check parser output before committing changes, or run a
                    sample ingest of your documents.
                  </p>
                </div>
                <ChevronDown
                  aria-hidden="true"
                  className={cn(
                    "mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 group-hover:text-foreground",
                    previewOpen && "rotate-180",
                  )}
                />
              </CollapsibleTrigger>
              <CollapsibleContent className="pt-4">
                <IngestPreviewSettingsSection />
              </CollapsibleContent>
            </section>
          </Collapsible>
        ) : null}
        <IngestSaveBar />
      </div>
    </IngestSaveProvider>
  );
}
