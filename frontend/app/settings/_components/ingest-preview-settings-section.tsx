"use client";

import { useState } from "react";
import { toast } from "sonner";
import { IngestPreviewAutoOpenControl } from "@/components/ingest-preview-auto-open-control";
import { IngestReviewDialog } from "@/components/ingest-review";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useIngestPreviewSettings } from "@/hooks/use-ingest-preview-settings";
import { uploadFile } from "@/lib/upload-utils";
import { cn } from "@/lib/utils";

const SAMPLE_TEXT = `OpenRAG ingest preview sample

This short document is used to demonstrate how files are parsed and
chunked before they are used for retrieval.

- Reading layout
- Creating chunks
- Generating embeddings
- Storing in OpenSearch
`;

function createSampleFile(): File {
  return new File([SAMPLE_TEXT], "ingest-preview-sample.txt", {
    type: "text/plain",
  });
}

export function IngestPreviewSettingsSection() {
  const { settings, updateSettings } = useIngestPreviewSettings();
  const [runningSample, setRunningSample] = useState(false);
  const [showPreviewDialog, setShowPreviewDialog] = useState(false);
  const [previewTaskId, setPreviewTaskId] = useState<string | null>(null);
  const [previewFile, setPreviewFile] = useState<File | null>(null);

  const runSampleIngest = async () => {
    const sample = createSampleFile();
    setPreviewFile(sample);
    setPreviewTaskId(null);
    setShowPreviewDialog(true);
    setRunningSample(true);

    try {
      const result = await uploadFile(sample, false, false, undefined, true);
      if (result.taskId) {
        setPreviewTaskId(result.taskId);
      }
      if (!result.previewMode) {
        setShowPreviewDialog(false);
        toast.error("Ingest preview is not available", {
          description:
            "Requires OSS/SaaS run mode and OPENRAG_INGEST_PREVIEW_ENABLED=true.",
        });
      }
    } catch (error) {
      setShowPreviewDialog(false);
      toast.error("Sample ingest failed", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    } finally {
      setRunningSample(false);
    }
  };

  return (
    <div className="space-y-0" data-testid="ingest-preview-settings">
      <div className="flex items-center justify-between gap-4 py-4 border-b border-border">
        <div className="flex-1 min-w-0">
          <Label className="text-base font-medium">
            Auto-open ingest preview
          </Label>
          <p className="text-sm text-muted-foreground mt-1">
            Open the review automatically when a document is ingested.
          </p>
        </div>
        <IngestPreviewAutoOpenControl
          value={settings.autoOpen}
          onChange={(autoOpen) => updateSettings({ autoOpen })}
          aria-label="Auto-open ingest preview"
        />
      </div>

      <SettingToggle
        id="show-chunk-boundaries"
        label="Show chunk boundaries"
        description="Show the indexed chunk list for each document."
        checked={settings.showChunkBoundaries}
        onCheckedChange={(checked) =>
          updateSettings({ showChunkBoundaries: checked })
        }
      />
      <SettingToggle
        id="show-indexing-pipeline"
        label="Show indexing pipeline"
        description="Reading layout, creating chunks, embeddings, stored."
        checked={settings.showIndexingPipeline}
        onCheckedChange={(checked) =>
          updateSettings({ showIndexingPipeline: checked })
        }
      />
      <SettingToggle
        id="show-chunk-contents"
        label="Show chunk contents"
        description="Stream each chunk's extracted text as it is created."
        checked={settings.showChunkContents}
        onCheckedChange={(checked) =>
          updateSettings({ showChunkContents: checked })
        }
      />
      <SettingToggle
        id="completion-notification"
        label="Completion notification"
        description="Show a 'Task completed' toast when ingestion finishes."
        checked={settings.completionNotification}
        onCheckedChange={(checked) =>
          updateSettings({ completionNotification: checked })
        }
        last
      />

      <div className="pt-6">
        <Button
          type="button"
          onClick={() => void runSampleIngest()}
          disabled={runningSample}
          data-testid="ingest-preview-run-sample"
        >
          {runningSample ? "Running sample…" : "Run a sample ingest"}
        </Button>
      </div>

      <IngestReviewDialog
        open={showPreviewDialog}
        onOpenChange={setShowPreviewDialog}
        taskIds={previewTaskId ? [previewTaskId] : []}
        filename={previewFile?.name}
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
        <Label htmlFor={id} className="text-base font-medium cursor-pointer">
          {label}
        </Label>
        <p className="text-sm text-muted-foreground mt-1">{description}</p>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  );
}
