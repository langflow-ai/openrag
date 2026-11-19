"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  useReimportPreflight,
  useReimportSnapshot,
} from "@/app/api/mutations/useSnapshotImportMutations";
import { useSnapshotSnapshotsQuery } from "@/app/api/queries/useSnapshotSnapshotsQuery";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { SnapshotImport } from "@/lib/opensearch-snapshot";
import { cn } from "@/lib/utils";
import {
  buildAnalyserUploads,
  missingAnalyserFiles,
  PreflightReport,
} from "./preflight-report";

function ReimportBody({
  imp,
  onClose,
}: {
  imp: SnapshotImport;
  onClose: () => void;
}) {
  const { data, isLoading, error } = useSnapshotSnapshotsQuery(imp.source_id);
  const preflight = useReimportPreflight();
  const reimport = useReimportSnapshot();
  const { mutate: runPreflight } = preflight;
  const [snapshot, setSnapshot] = useState<string | null>(null);
  const [contents, setContents] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!snapshot) return;
    setContents({});
    runPreflight({ importId: imp.id, snapshot });
  }, [runPreflight, imp.id, snapshot]);

  const result = preflight.data;
  const missing = result
    ? missingAnalyserFiles(result.analyser_files, contents)
    : [];
  const canConfirm =
    !!result &&
    result.ok &&
    result.blockers.length === 0 &&
    missing.length === 0 &&
    !reimport.isPending;

  const confirm = async () => {
    if (!result || !snapshot) return;
    try {
      await reimport.mutateAsync({
        importId: imp.id,
        snapshot,
        analyserFiles: buildAnalyserUploads(result.analyser_files, contents),
      });
      toast.success(`Re-import of ${imp.name} started`);
      onClose();
    } catch {
      // Rendered below from `reimport.error`.
    }
  };

  return (
    <>
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">
          The current datasets keep serving until the new copy is ready, then
          switch over in one step. The same indices must exist in the snapshot.
        </p>
        {isLoading && (
          <p role="status" className="text-sm text-muted-foreground">
            Loading snapshots…
          </p>
        )}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
        )}
        <fieldset className="space-y-2">
          <legend className="mb-2 text-sm font-medium">New snapshot</legend>
          {(data?.snapshots ?? []).map((candidate) => (
            <label
              key={candidate.uuid}
              className={cn(
                "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 text-sm hover:bg-muted",
                candidate.name === snapshot && "border-primary bg-muted",
              )}
            >
              <input
                type="radio"
                name="reimport-snapshot"
                className="accent-primary"
                checked={candidate.name === snapshot}
                onChange={() => setSnapshot(candidate.name)}
              />
              <span className="font-medium">{candidate.name}</span>
              {candidate.name === imp.snapshot_name && (
                <span className="ml-auto text-xs text-muted-foreground">
                  current
                </span>
              )}
            </label>
          ))}
        </fieldset>

        {preflight.isPending && (
          <div
            role="status"
            className="flex items-center gap-2 text-sm text-muted-foreground"
          >
            <Loader2 className="h-4 w-4 animate-spin" />
            Running preflight checks…
          </div>
        )}
        {preflight.error && (
          <Alert variant="destructive">
            <AlertDescription>{preflight.error.message}</AlertDescription>
          </Alert>
        )}
        {result && (
          <PreflightReport
            result={result}
            contents={contents}
            onContentChange={(key, content) =>
              setContents((current) => {
                const next = { ...current };
                if (content === undefined) delete next[key];
                else next[key] = content;
                return next;
              })
            }
          />
        )}
        {reimport.error && (
          <Alert variant="destructive">
            <AlertDescription>{reimport.error.message}</AlertDescription>
          </Alert>
        )}
      </div>
      <DialogFooter className="mt-4">
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button disabled={!canConfirm} onClick={confirm}>
          {reimport.isPending ? "Starting…" : "Start re-import"}
        </Button>
      </DialogFooter>
    </>
  );
}

export function ReimportDialog({
  imp,
  onClose,
}: {
  imp: SnapshotImport | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={imp !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Re-import {imp?.name}</DialogTitle>
          <DialogDescription>
            Replace this import's data with a newer snapshot.
          </DialogDescription>
        </DialogHeader>
        {imp && <ReimportBody imp={imp} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}
