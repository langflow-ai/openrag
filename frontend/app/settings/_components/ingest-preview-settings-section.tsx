"use client";

import { useMemo, useState } from "react";
import { IngestPreviewAutoOpenControl } from "@/components/ingest-preview-auto-open-control";
import { IngestReviewDialog } from "@/components/ingest-review";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useRegisterDirty } from "@/contexts/unsaved-changes-context";
import {
  INGEST_PREVIEW_AUTO_OPEN_OPTIONS,
  type IngestPreviewSettings,
  useIngestPreviewSettings,
} from "@/hooks/use-ingest-preview-settings";
import { createSampleDemoFile } from "@/lib/ingest-preview-demo";
import { useRegisterSave } from "./ingest-save-context";

const EMPTY_PREVIEW_FILES: File[] = [];

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

  const isDirty = draft.autoOpen !== settings.autoOpen;
  useRegisterDirty("ingest-preview", isDirty);

  const autoOpenDescription =
    INGEST_PREVIEW_AUTO_OPEN_OPTIONS.find(
      (option) => option.value === draft.autoOpen,
    )?.description ?? INGEST_PREVIEW_AUTO_OPEN_OPTIONS[0].description;
  const previewFiles = useMemo(
    () => (previewFile ? [previewFile] : EMPTY_PREVIEW_FILES),
    [previewFile],
  );

  // The tab's single Save button drives this; it reports success for the whole
  // tab, so this only persists.
  useRegisterSave("ingest-preview", {
    isDirty,
    blocked: false,
    save: () => {
      updateSettings({ autoOpen: draft.autoOpen });
    },
  });

  const runSampleIngest = () => {
    setPreviewFile(createSampleDemoFile());
    setShowPreviewDialog(true);
  };

  return (
    <div className="space-y-0" data-testid="ingest-preview-settings">
      <div className="flex items-center justify-between gap-12 border-b border-border py-6">
        <div className="flex-1 min-w-0 space-y-1.5">
          <Label className="text-base font-semibold">
            Auto-open ingest preview
          </Label>
          <p className="text-sm text-muted-foreground">{autoOpenDescription}</p>
        </div>
        <IngestPreviewAutoOpenControl
          value={draft.autoOpen}
          onChange={(autoOpen) => setDraft((prev) => ({ ...prev, autoOpen }))}
          aria-label="Auto-open ingest preview"
        />
      </div>

      <div className="flex items-center justify-between gap-8 py-6">
        <div className="flex-1 min-w-0 space-y-1.5">
          <p className="text-base font-semibold">Sample ingest</p>
          <p className="text-sm text-muted-foreground">
            Test out the document parser.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={runSampleIngest}
          data-testid="ingest-preview-run-sample"
        >
          Run sample ingest
        </Button>
      </div>

      <IngestReviewDialog
        open={showPreviewDialog}
        onOpenChange={setShowPreviewDialog}
        demo
        settingsOverride={draft}
        previewFiles={previewFiles}
      />
    </div>
  );
}
