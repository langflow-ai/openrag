"use client";

import { Pencil, Plus } from "lucide-react";
import { useState } from "react";
import {
  useCreateSnapshotSource,
  useDeleteSnapshotSource,
  useUpdateSnapshotSource,
} from "@/app/api/mutations/useSnapshotSourceMutations";
import { useSnapshotSourcesQuery } from "@/app/api/queries/useSnapshotSourcesQuery";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { usePermissions } from "@/hooks/use-permissions";
import type { SnapshotSource } from "@/lib/opensearch-snapshot";
import { cn } from "@/lib/utils";

interface SourceForm {
  name: string;
  bucket: string;
  prefix: string;
  region: string;
  endpoint_url: string;
  access_key: string;
  secret_key: string;
  path_style: boolean;
  verify_tls: boolean;
}

const EMPTY_FORM: SourceForm = {
  name: "",
  bucket: "",
  prefix: "",
  region: "us-east-1",
  endpoint_url: "",
  access_key: "",
  secret_key: "",
  path_style: true,
  verify_tls: true,
};

function formFromSource(source: SnapshotSource): SourceForm {
  return {
    name: source.name,
    bucket: source.bucket,
    prefix: source.prefix,
    region: source.region,
    endpoint_url: source.endpoint_url ?? "",
    access_key: "",
    secret_key: "",
    path_style: source.path_style,
    verify_tls: source.verify_tls,
  };
}

interface SourceStepProps {
  selectedId: string | null;
  onSelect: (sourceId: string | null) => void;
  onContinue: () => void;
}

export function SourceStep({
  selectedId,
  onSelect,
  onContinue,
}: SourceStepProps) {
  const { can, canAny } = usePermissions();
  const canCreate = can("connectors:create");
  const canDelete = canAny(["connectors:delete:own", "connectors:delete:any"]);
  const { data: sources = [], isLoading, error } = useSnapshotSourcesQuery();
  const createSource = useCreateSnapshotSource();
  const updateSource = useUpdateSnapshotSource();
  const deleteSource = useDeleteSnapshotSource();

  // `null` = list; "new" = create form; otherwise the source being edited.
  const [editing, setEditing] = useState<SnapshotSource | "new" | null>(null);
  const [form, setForm] = useState<SourceForm>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);

  const showForm = editing !== null || (!isLoading && sources.length === 0);
  const editingSource = editing && editing !== "new" ? editing : null;
  const isSaving = createSource.isPending || updateSource.isPending;

  const update = <K extends keyof SourceForm>(key: K, value: SourceForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const openForm = (target: SnapshotSource | "new") => {
    setForm(target === "new" ? EMPTY_FORM : formFromSource(target));
    setFormError(null);
    setEditing(target);
  };

  const closeForm = () => {
    setEditing(null);
    setFormError(null);
  };

  const formValid = form.name.trim() !== "" && form.bucket.trim() !== "";

  const save = async () => {
    setFormError(null);
    const input = {
      name: form.name.trim(),
      bucket: form.bucket.trim(),
      prefix: form.prefix.trim(),
      region: form.region.trim() || "us-east-1",
      // Omission keeps the stored endpoint on update, so clearing must send null.
      ...(form.endpoint_url.trim()
        ? { endpoint_url: form.endpoint_url.trim() }
        : editingSource && { endpoint_url: null }),
      // Omitted credentials mean "keep" on update and "none" on create.
      ...(form.access_key && { access_key: form.access_key }),
      ...(form.secret_key && { secret_key: form.secret_key }),
      path_style: form.path_style,
      verify_tls: form.verify_tls,
    };
    try {
      const saved = editingSource
        ? await updateSource.mutateAsync({ id: editingSource.id, input })
        : await createSource.mutateAsync(input);
      onSelect(saved.id);
      closeForm();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save");
    }
  };

  const remove = async (source: SnapshotSource) => {
    setFormError(null);
    try {
      await deleteSource.mutateAsync(source.id);
      if (selectedId === source.id) onSelect(null);
      closeForm();
    } catch (err) {
      setFormError(
        err instanceof Error ? err.message : "Could not delete the source",
      );
    }
  };

  if (showForm) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Point OpenRAG at the S3 location that holds an OpenSearch snapshot
          repository. Keys are stored encrypted and never shown again.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="snapshot-source-name">Source name</Label>
            <Input
              id="snapshot-source-name"
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="snapshot-source-bucket">Bucket</Label>
            <Input
              id="snapshot-source-bucket"
              value={form.bucket}
              onChange={(e) => update("bucket", e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="snapshot-source-prefix">Prefix</Label>
            <Input
              id="snapshot-source-prefix"
              value={form.prefix}
              placeholder="path/to/repository"
              onChange={(e) => update("prefix", e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="snapshot-source-region">Region</Label>
            <Input
              id="snapshot-source-region"
              value={form.region}
              onChange={(e) => update("region", e.target.value)}
            />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="snapshot-source-endpoint">
              Endpoint URL (optional)
            </Label>
            <Input
              id="snapshot-source-endpoint"
              value={form.endpoint_url}
              placeholder="https://s3.example.com"
              onChange={(e) => update("endpoint_url", e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="snapshot-source-access-key">Access key</Label>
            <Input
              id="snapshot-source-access-key"
              autoComplete="off"
              value={form.access_key}
              placeholder={editingSource?.has_credentials ? "Unchanged" : ""}
              onChange={(e) => update("access_key", e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="snapshot-source-secret-key">Secret key</Label>
            <Input
              id="snapshot-source-secret-key"
              type="password"
              autoComplete="new-password"
              value={form.secret_key}
              placeholder={editingSource?.has_credentials ? "Unchanged" : ""}
              onChange={(e) => update("secret_key", e.target.value)}
            />
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id="snapshot-source-path-style"
              checked={form.path_style}
              onCheckedChange={(value) => update("path_style", value)}
            />
            <Label htmlFor="snapshot-source-path-style">
              Path-style addressing
            </Label>
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id="snapshot-source-verify-tls"
              checked={form.verify_tls}
              onCheckedChange={(value) => update("verify_tls", value)}
            />
            <Label htmlFor="snapshot-source-verify-tls">
              Verify TLS certificates
            </Label>
          </div>
        </div>
        {formError && (
          <Alert variant="destructive">
            <AlertDescription>{formError}</AlertDescription>
          </Alert>
        )}
        <div className="flex flex-wrap justify-between gap-2">
          <div>
            {editingSource && canDelete && (
              <Button
                variant="outline"
                className="text-destructive hover:text-destructive"
                disabled={deleteSource.isPending}
                onClick={() => remove(editingSource)}
              >
                Delete source
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            {sources.length > 0 && (
              <Button variant="outline" onClick={closeForm}>
                Cancel
              </Button>
            )}
            <Button
              disabled={!formValid || isSaving || !canCreate}
              title={
                canCreate
                  ? undefined
                  : "You do not have permission to create connectors"
              }
              onClick={save}
            >
              {isSaving
                ? "Testing connection…"
                : editingSource
                  ? "Save source"
                  : "Save and test source"}
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Choose the S3 location that holds the snapshot repository.
      </p>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      )}
      <ul className="space-y-2" aria-label="Snapshot sources">
        {sources.map((source) => (
          <li key={source.id} className="flex items-center gap-2">
            <button
              type="button"
              aria-pressed={selectedId === source.id}
              onClick={() => onSelect(source.id)}
              className={cn(
                "flex-1 rounded-lg border px-3 py-2 text-left text-sm transition-colors hover:bg-muted",
                selectedId === source.id && "border-primary bg-muted",
              )}
            >
              <span className="font-medium">{source.name}</span>
              <span className="block text-xs text-muted-foreground">
                s3://{source.bucket}
                {source.prefix ? `/${source.prefix}` : ""}
              </span>
            </button>
            <Button
              variant="outline"
              size="iconMd"
              aria-label={`Edit ${source.name}`}
              onClick={() => openForm(source)}
            >
              <Pencil className="h-4 w-4" />
            </Button>
          </li>
        ))}
      </ul>
      <div className="flex justify-between gap-2">
        <Button
          variant="outline"
          disabled={!canCreate}
          title={
            canCreate
              ? undefined
              : "You do not have permission to create connectors"
          }
          onClick={() => openForm("new")}
        >
          <Plus className="h-4 w-4" />
          New source
        </Button>
        <Button disabled={!selectedId} onClick={onContinue}>
          Continue
        </Button>
      </div>
    </div>
  );
}
