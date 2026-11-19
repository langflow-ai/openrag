"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import {
  usePreflightSnapshot,
  useStartSnapshotImport,
} from "@/app/api/mutations/useSnapshotImportMutations";
import { useSnapshotStatusQuery } from "@/app/api/queries/useSnapshotStatusQuery";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { usePermissions } from "@/hooks/use-permissions";
import { SnapshotApiError } from "@/lib/opensearch-snapshot";
import {
  buildAnalyserUploads,
  missingAnalyserFiles,
  PreflightReport,
} from "./preflight-report";

interface PreflightStepProps {
  sourceId: string;
  snapshot: string;
  indices: string[];
  onBack: () => void;
  onStarted: (importId: string) => void;
}

export function PreflightStep({
  sourceId,
  snapshot,
  indices,
  onBack,
  onStarted,
}: PreflightStepProps) {
  const { can } = usePermissions();
  const canCreate = can("connectors:create");
  const { data: status } = useSnapshotStatusQuery();
  const privateSupported = status?.private_supported ?? true;

  const preflight = usePreflightSnapshot();
  const startImport = useStartSnapshotImport();
  const { mutate: runPreflight } = preflight;

  const [contents, setContents] = useState<Record<string, string>>({});
  const [name, setName] = useState(snapshot);
  const [sharedChoice, setSharedChoice] = useState(false);
  const shared = privateSupported ? sharedChoice : true;
  const indicesKey = indices.join("\u0000");

  // biome-ignore lint/correctness/useExhaustiveDependencies: indicesKey is the stable identity of `indices`
  useEffect(() => {
    setContents({});
    runPreflight({ sourceId, snapshot, indices });
  }, [runPreflight, sourceId, snapshot, indicesKey]);

  const result = preflight.data;
  const missing = result
    ? missingAnalyserFiles(result.analyser_files, contents)
    : [];
  const canStart =
    canCreate &&
    !!result &&
    result.ok &&
    result.blockers.length === 0 &&
    missing.length === 0 &&
    name.trim() !== "" &&
    !startImport.isPending &&
    !preflight.isPending;

  const start = async () => {
    if (!result) return;
    try {
      const accepted = await startImport.mutateAsync({
        source_id: sourceId,
        snapshot,
        indices,
        name: name.trim(),
        shared,
        analyser_files: buildAnalyserUploads(result.analyser_files, contents),
      });
      onStarted(accepted.import.id);
    } catch {
      // Surfaced below through `startImport.error`.
    }
  };

  const startError = startImport.error;
  const preflightError = preflight.error;

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        Checking <span className="font-medium">{snapshot}</span> (
        {indices.length} {indices.length === 1 ? "index" : "indices"}).
      </p>

      {preflight.isPending && (
        <div
          role="status"
          className="flex items-center gap-2 text-sm text-muted-foreground"
        >
          <Loader2 className="h-4 w-4 animate-spin" />
          Running preflight checks…
        </div>
      )}

      {preflightError && (
        <Alert variant="destructive">
          <AlertDescription className="flex items-center justify-between gap-2">
            {preflightError.message}
            <Button
              variant="outline"
              size="sm"
              onClick={() => runPreflight({ sourceId, snapshot, indices })}
            >
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {result && (
        <>
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

          <div className="space-y-1.5">
            <Label htmlFor="snapshot-import-name">Import name</Label>
            <Input
              id="snapshot-import-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div className="flex items-start gap-3">
            <Switch
              id="snapshot-import-shared"
              checked={shared}
              disabled={!privateSupported}
              onCheckedChange={setSharedChoice}
            />
            <div className="space-y-0.5">
              <Label htmlFor="snapshot-import-shared">
                Share with all OpenRAG users
              </Label>
              <p className="text-xs text-muted-foreground">
                {privateSupported
                  ? "Off: only you can search these datasets."
                  : "This deployment cannot restrict datasets to a single user, so every import is shared."}
              </p>
            </div>
          </div>
        </>
      )}

      {startError && (
        <Alert variant="destructive">
          <AlertDescription>
            {startError.message}
            {startError instanceof SnapshotApiError &&
              startError.blockers.length > 0 && (
                <ul className="mt-1 list-disc pl-4">
                  {startError.blockers.map((issue) => (
                    <li key={`${issue.code}-${issue.index ?? ""}`}>
                      {issue.message}
                    </li>
                  ))}
                </ul>
              )}
          </AlertDescription>
        </Alert>
      )}

      <div className="flex justify-between gap-2">
        <Button variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button
          disabled={!canStart}
          title={
            canCreate
              ? undefined
              : "You do not have permission to create connectors"
          }
          onClick={start}
        >
          {startImport.isPending ? "Starting…" : "Start import"}
        </Button>
      </div>
    </div>
  );
}
