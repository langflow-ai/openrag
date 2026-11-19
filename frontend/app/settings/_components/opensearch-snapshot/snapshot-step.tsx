"use client";

import { useSnapshotSnapshotsQuery } from "@/app/api/queries/useSnapshotSnapshotsQuery";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { formatBytes, type SnapshotSummary } from "@/lib/opensearch-snapshot";
import { cn } from "@/lib/utils";

/** Regular indices are pre-checked; system indices (`.`-prefixed) are not. */
export function defaultIndexSelection(snapshot: SnapshotSummary): string[] {
  return snapshot.indices
    .filter((index) => !index.name.startsWith("."))
    .map((index) => index.name);
}

interface SnapshotStepProps {
  sourceId: string;
  snapshotName: string | null;
  indices: string[];
  onChange: (snapshotName: string, indices: string[]) => void;
  onBack: () => void;
  onContinue: () => void;
}

export function SnapshotStep({
  sourceId,
  snapshotName,
  indices,
  onChange,
  onBack,
  onContinue,
}: SnapshotStepProps) {
  const { data, isLoading, error, refetch } =
    useSnapshotSnapshotsQuery(sourceId);
  const snapshots = data?.snapshots ?? [];
  const selected = snapshots.find((s) => s.name === snapshotName) ?? null;

  const toggleIndex = (name: string, checked: boolean) => {
    if (!selected) return;
    const next = new Set(indices);
    if (checked) next.add(name);
    else next.delete(name);
    // Keep the snapshot's own ordering so the request is deterministic.
    onChange(
      selected.name,
      selected.indices.map((i) => i.name).filter((n) => next.has(n)),
    );
  };

  return (
    <div className="space-y-5">
      {isLoading && (
        <div className="space-y-2" role="status" aria-label="Loading snapshots">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      )}
      {error && (
        <Alert variant="destructive">
          <AlertDescription className="flex items-center justify-between gap-2">
            {error.message}
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {data && snapshots.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No successful snapshots were found at this location.
        </p>
      )}
      {snapshots.length > 0 && (
        <fieldset className="space-y-2">
          <legend className="mb-2 text-sm font-medium">Snapshot</legend>
          {snapshots.map((snapshot) => (
            <label
              key={snapshot.uuid}
              className={cn(
                "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 text-sm transition-colors hover:bg-muted",
                snapshot.name === snapshotName && "border-primary bg-muted",
              )}
            >
              <input
                type="radio"
                name="snapshot"
                className="accent-primary"
                checked={snapshot.name === snapshotName}
                onChange={() =>
                  onChange(snapshot.name, defaultIndexSelection(snapshot))
                }
              />
              <span className="font-medium">{snapshot.name}</span>
              <span className="ml-auto text-xs text-muted-foreground">
                {snapshot.indices.length} indices · written by{" "}
                {snapshot.version || "unknown version"}
                {snapshot.state !== "SUCCESS" && ` · ${snapshot.state}`}
              </span>
            </label>
          ))}
        </fieldset>
      )}
      {selected && (
        <fieldset className="space-y-2">
          <legend className="mb-2 text-sm font-medium">
            Indices to import
          </legend>
          {selected.indices.map((index) => {
            const id = `snapshot-index-${index.name}`;
            return (
              <div key={index.name} className="flex items-center gap-3">
                <Checkbox
                  id={id}
                  checked={indices.includes(index.name)}
                  onCheckedChange={(checked) =>
                    toggleIndex(index.name, checked === true)
                  }
                />
                <Label htmlFor={id} className="font-mono text-sm">
                  {index.name}
                </Label>
                {typeof index.size_bytes === "number" &&
                  index.size_bytes > 0 && (
                    <span className="ml-auto text-xs text-muted-foreground">
                      {formatBytes(index.size_bytes)}
                    </span>
                  )}
              </div>
            );
          })}
        </fieldset>
      )}
      <div className="flex justify-between gap-2">
        <Button variant="outline" onClick={onBack}>
          Back
        </Button>
        <Button
          disabled={!selected || indices.length === 0}
          onClick={onContinue}
        >
          Continue
        </Button>
      </div>
    </div>
  );
}
