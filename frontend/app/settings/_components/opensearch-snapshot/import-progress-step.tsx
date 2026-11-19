"use client";

import { Loader2 } from "lucide-react";
import { useSnapshotImportQuery } from "@/app/api/queries/useSnapshotImportQuery";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/opensearch-snapshot";
import { MappingStep } from "./mapping-step";

const PROGRESS_LABELS: Record<string, string> = {
  staging: "Copying snapshot files…",
  restoring: "Restoring indices…",
  deleting: "Deleting import…",
};

interface ImportProgressStepProps {
  importId: string;
  pollIntervalMs?: number;
  onDone: () => void;
}

/** Polls the import until it reaches `review`, then hands over to mapping. */
export function ImportProgressStep({
  importId,
  pollIntervalMs,
  onDone,
}: ImportProgressStepProps) {
  const { data: imp, error } = useSnapshotImportQuery(importId, pollIntervalMs);

  if (error && !imp) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }
  if (!imp) {
    return (
      <div role="status" className="text-sm text-muted-foreground">
        Loading import…
      </div>
    );
  }

  if (imp.status === "review" || imp.status === "active") {
    return <MappingStep imp={imp} onDone={onDone} />;
  }

  if (imp.status === "failed") {
    return (
      <div className="space-y-4">
        <Alert variant="destructive">
          <AlertTitle>Import failed</AlertTitle>
          <AlertDescription>
            {imp.job.error ?? "The import did not complete."}
          </AlertDescription>
        </Alert>
        <div className="flex justify-end">
          <Button variant="outline" onClick={onDone}>
            Close
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div role="status" className="space-y-2">
      <div className="flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {PROGRESS_LABELS[imp.status] ?? "Working…"}
      </div>
      <p className="text-xs text-muted-foreground">
        {imp.name}
        {imp.staged_bytes > 0 && ` · ${formatBytes(imp.staged_bytes)} copied`}.
        You can close this window; the import keeps running.
      </p>
    </div>
  );
}
