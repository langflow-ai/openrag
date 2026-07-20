"use client";

import { useState } from "react";
import { toast } from "sonner";
import { IngestPreviewAutoOpenControl } from "@/components/ingest-preview-auto-open-control";
import { IngestReviewDialog } from "@/components/ingest-review";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  type IngestPreviewSettings,
  useIngestPreviewSettings,
} from "@/hooks/use-ingest-preview-settings";
import { createSampleDemoFile } from "@/lib/ingest-preview-demo";
import { cn } from "@/lib/utils";

const INGEST_PREVIEW_SETTING_KEYS = [
  "autoOpen",
  "showChunkBoundaries",
  "showIndexingPipeline",
  "showChunkContents",
  "completionNotification",
] as const satisfies ReadonlyArray<keyof IngestPreviewSettings>;

function settingsEqual(
  a: IngestPreviewSettings,
  b: IngestPreviewSettings,
): boolean {
  return INGEST_PREVIEW_SETTING_KEYS.every((key) => a[key] === b[key]);
}

export function IngestPreviewSettingsSection() {
  const { settings, updateSettings } = useIngestPreviewSettings();
  const [draft, setDraft] = useState<IngestPreviewSettings>(settings);
  const [prevSettings, setPrevSettings] = useState(settings);
  const [showPreviewDialog, setShowPreviewDialog] = useState(false);
  const [previewFile, setPreviewFile] = useState<File | null>(null);

  // Hook hydrates from localStorage after mount — keep the form in sync when
  // persisted values change (including after Save). Adjust during render instead
  // of an effect: https://react.dev/learn/you-might-not-need-an-effect
  if (settings !== prevSettings) {
    setPrevSettings(settings);
    setDraft(settings);
  }

  const isDirty = !settingsEqual(draft, settings);

  const patchDraft = (patch: Partial<IngestPreviewSettings>) => {
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  const saveChanges = () => {
    updateSettings(draft);
    toast.success("Ingest preview settings saved");
  };

  const runSampleIngest = () => {
    setPreviewFile(createSampleDemoFile());
    setShowPreviewDialog(true);
  };

  return (
    <div className="space-y-0" data-testid="ingest-preview-settings">
      <div className="flex items-center justify-between gap-4 py-4 border-b border-border">
        <div className="flex-1 min-w-0">
          <Label className="text-base font-medium">
            Auto-open ingest preview
          </Label>
          <p className="text-sm text-muted-foreground mt-1">
            Controls Knowledge uploads. Onboarding always opens the review when
            the feature is enabled; Onboarding only skips Knowledge auto-open.
          </p>
        </div>
        <IngestPreviewAutoOpenControl
          value={draft.autoOpen}
          onChange={(autoOpen) => patchDraft({ autoOpen })}
          aria-label="Auto-open ingest preview"
        />
      </div>

      <SettingToggle
        id="show-chunk-boundaries"
        label="Show chunk boundaries"
        description="Show the indexed chunk list for each document."
        checked={draft.showChunkBoundaries}
        onCheckedChange={(checked) =>
          patchDraft({ showChunkBoundaries: checked })
        }
      />
      <SettingToggle
        id="show-indexing-pipeline"
        label="Show indexing pipeline"
        description="Reading layout, creating chunks, embeddings, stored."
        checked={draft.showIndexingPipeline}
        onCheckedChange={(checked) =>
          patchDraft({ showIndexingPipeline: checked })
        }
      />
      <SettingToggle
        id="show-chunk-contents"
        label="Show chunk contents"
        description="Stream each chunk's extracted text as it is created."
        checked={draft.showChunkContents}
        onCheckedChange={(checked) =>
          patchDraft({ showChunkContents: checked })
        }
      />
      <SettingToggle
        id="completion-notification"
        label="Completion notification"
        description="Show a 'Task completed' toast when ingestion finishes."
        checked={draft.completionNotification}
        onCheckedChange={(checked) =>
          patchDraft({ completionNotification: checked })
        }
        last
      />

      <div className="flex flex-wrap items-center justify-end gap-2 pt-6">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={runSampleIngest}
          data-testid="ingest-preview-run-sample"
        >
          Run a sample ingest
        </Button>
        <Button
          type="button"
          size="sm"
          className="min-w-[120px]"
          onClick={saveChanges}
          disabled={!isDirty}
          data-testid="ingest-preview-save"
        >
          Save changes
        </Button>
      </div>

      <IngestReviewDialog
        open={showPreviewDialog}
        onOpenChange={setShowPreviewDialog}
        demo
        settingsOverride={draft}
        previewFiles={previewFile ? [previewFile] : []}
      />
    </div>
  );
}

function SettingToggle({
  id,
  label,
  description,
  checked,
  onCheckedChange,
  last = false,
}: {
  id: string;
  label: string;
  description: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  last?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-4 py-4",
        !last && "border-b border-border",
      )}
    >
      <div className="flex-1 min-w-0">
        <Label htmlFor={id} className="text-base font-medium">
          {label}
        </Label>
        <p className="text-sm text-muted-foreground mt-1">{description}</p>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  );
}
