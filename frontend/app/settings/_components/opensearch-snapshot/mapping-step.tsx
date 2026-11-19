"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  type DatasetPatch,
  useActivateSnapshotImport,
  usePatchSnapshotDataset,
} from "@/app/api/mutations/useSnapshotImportMutations";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  SnapshotApiError,
  type SnapshotDataset,
  type SnapshotImport,
} from "@/lib/opensearch-snapshot";

const NONE = "__none__";

/** Mapping types the backend accepts for text/title/URL fields. */
const STRING_FIELD_TYPES = new Set([
  "text",
  "match_only_text",
  "search_as_you_type",
  "keyword",
  "constant_keyword",
  "wildcard",
]);

export interface DatasetDraft {
  display_name: string;
  description: string;
  text_fields: string[];
  title_field: string;
  url_field: string;
  mode: "lexical" | "hybrid";
  vector_field: string;
  /** Qualified `provider:model` id. */
  model: string;
}

function qualifiedModel(dataset: SnapshotDataset): string {
  const { provider, model } = dataset.retrieval;
  if (!model) return "";
  return provider ? `${provider}:${model}` : model;
}

export function draftFromDataset(dataset: SnapshotDataset): DatasetDraft {
  const hybrid =
    dataset.retrieval.mode === "hybrid" && dataset.vector_fields.length > 0;
  return {
    display_name: dataset.display_name,
    description: dataset.description,
    text_fields: dataset.field_map.text_fields ?? [],
    title_field: dataset.field_map.title_field ?? "",
    url_field: dataset.field_map.url_field ?? "",
    mode: hybrid ? "hybrid" : "lexical",
    vector_field: dataset.retrieval.vector_field ?? "",
    model: qualifiedModel(dataset),
  };
}

export function patchFromDraft(
  dataset: SnapshotDataset,
  draft: DatasetDraft,
): DatasetPatch {
  const vector = dataset.vector_fields.find(
    (field) => field.name === draft.vector_field,
  );
  const separator = draft.model.indexOf(":");
  const retrieval =
    draft.mode === "hybrid"
      ? {
          ...dataset.retrieval,
          mode: "hybrid" as const,
          vector_field: draft.vector_field,
          provider: separator > 0 ? draft.model.slice(0, separator) : "",
          model: separator > 0 ? draft.model.slice(separator + 1) : draft.model,
          dims: vector?.dims ?? null,
        }
      : { mode: "lexical" as const };
  return {
    display_name: draft.display_name.trim(),
    description: draft.description.trim(),
    field_map: {
      ...dataset.field_map,
      text_fields: draft.text_fields,
      title_field: draft.title_field || null,
      url_field: draft.url_field || null,
    },
    retrieval,
  };
}

function draftValid(draft: DatasetDraft): boolean {
  if (!draft.display_name.trim() || draft.text_fields.length === 0) {
    return false;
  }
  return draft.mode === "lexical" || (!!draft.vector_field && !!draft.model);
}

function FieldSelect({
  id,
  label,
  value,
  options,
  onChange,
  allowNone = true,
}: {
  id: string;
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  allowNone?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Select
        value={value === "" ? (allowNone ? NONE : undefined) : value}
        onValueChange={(next) => onChange(next === NONE ? "" : next)}
      >
        <SelectTrigger id={id}>
          <SelectValue placeholder="Select…" />
        </SelectTrigger>
        <SelectContent>
          {allowNone && <SelectItem value={NONE}>None</SelectItem>}
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function DatasetForm({
  importId,
  dataset,
  draft,
  onDraftChange,
  onSaved,
  readOnly,
}: {
  importId: string;
  dataset: SnapshotDataset;
  draft: DatasetDraft;
  onDraftChange: (draft: DatasetDraft) => void;
  onSaved: (submitted: DatasetDraft, saved: SnapshotDataset) => void;
  readOnly: boolean;
}) {
  const patch = usePatchSnapshotDataset();
  const [error, setError] = useState<string | null>(null);
  const dirty =
    JSON.stringify(draft) !== JSON.stringify(draftFromDataset(dataset));
  const prefix = `dataset-${dataset.id}`;
  const textFieldOptions = dataset.fields.filter(
    (field) =>
      STRING_FIELD_TYPES.has(field.type) &&
      !dataset.vector_fields.some((vector) => vector.name === field.name),
  );
  const fieldOptions = textFieldOptions.map((field) => ({
    value: field.name,
    label: `${field.name} (${field.type})`,
  }));
  const hasVectors = dataset.vector_fields.length > 0;

  const set = <K extends keyof DatasetDraft>(key: K, value: DatasetDraft[K]) =>
    onDraftChange({ ...draft, [key]: value });

  const save = async () => {
    setError(null);
    try {
      const saved = await patch.mutateAsync({
        importId,
        datasetId: dataset.id,
        patch: patchFromDraft(dataset, draft),
      });
      onSaved(draft, saved);
      toast.success(`Saved ${draft.display_name.trim()}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    }
  };

  return (
    <section
      aria-label={`Dataset ${dataset.source_index}`}
      className="space-y-4 rounded-lg border p-4"
    >
      <div className="flex items-baseline justify-between gap-2">
        <h4 className="font-mono text-sm font-semibold">
          {dataset.source_index}
        </h4>
        <span className="text-xs text-muted-foreground">
          {dataset.doc_count ?? "?"} documents
        </span>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor={`${prefix}-name`}>
            Display name for {dataset.source_index}
          </Label>
          <Input
            id={`${prefix}-name`}
            value={draft.display_name}
            disabled={readOnly}
            onChange={(e) => set("display_name", e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${prefix}-description`}>
            Description for {dataset.source_index}
          </Label>
          <Textarea
            id={`${prefix}-description`}
            rows={2}
            value={draft.description}
            disabled={readOnly}
            onChange={(e) => set("description", e.target.value)}
          />
        </div>
      </div>

      <fieldset className="space-y-2" disabled={readOnly}>
        <legend className="mb-1 text-sm font-medium">Text fields</legend>
        <p className="text-xs text-muted-foreground">
          Fields searched and shown as the content of each result.
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {fieldOptions.map((option) => {
            const id = `${prefix}-text-${option.value}`;
            return (
              <div key={option.value} className="flex items-center gap-2">
                <Checkbox
                  id={id}
                  checked={draft.text_fields.includes(option.value)}
                  onCheckedChange={(checked) =>
                    set(
                      "text_fields",
                      checked === true
                        ? [...draft.text_fields, option.value]
                        : draft.text_fields.filter((f) => f !== option.value),
                    )
                  }
                />
                <Label htmlFor={id} className="font-mono text-xs">
                  {option.label}
                </Label>
              </div>
            );
          })}
        </div>
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <FieldSelect
          id={`${prefix}-title`}
          label={`Title field for ${dataset.source_index}`}
          value={draft.title_field}
          options={fieldOptions}
          onChange={(value) => set("title_field", value)}
        />
        <FieldSelect
          id={`${prefix}-url`}
          label={`URL field for ${dataset.source_index}`}
          value={draft.url_field}
          options={fieldOptions}
          onChange={(value) => set("url_field", value)}
        />
      </div>

      {hasVectors && (
        <fieldset className="space-y-3" disabled={readOnly}>
          <legend className="mb-1 text-sm font-medium">Hybrid search</legend>
          <div className="flex items-center gap-2">
            <Checkbox
              id={`${prefix}-hybrid`}
              checked={draft.mode === "hybrid"}
              onCheckedChange={(checked) =>
                onDraftChange({
                  ...draft,
                  mode: checked === true ? "hybrid" : "lexical",
                  vector_field:
                    draft.vector_field || dataset.vector_fields[0]?.name || "",
                })
              }
            />
            <Label htmlFor={`${prefix}-hybrid`}>
              Combine keyword and vector search for {dataset.source_index}
            </Label>
          </div>
          {draft.mode === "hybrid" && (
            <div className="grid gap-4 sm:grid-cols-2">
              <FieldSelect
                id={`${prefix}-vector`}
                label={`Vector field for ${dataset.source_index}`}
                value={draft.vector_field}
                allowNone={false}
                options={dataset.vector_fields.map((field) => ({
                  value: field.name,
                  label: `${field.name} (${field.dims ?? "?"} dims${field.engine ? `, ${field.engine}` : ""})`,
                }))}
                onChange={(value) => set("vector_field", value)}
              />
              <FieldSelect
                id={`${prefix}-model`}
                label={`Embedding model for ${dataset.source_index}`}
                value={draft.model}
                allowNone={false}
                options={dataset.available_models.map((model) => ({
                  value: model,
                  label: model,
                }))}
                onChange={(value) => set("model", value)}
              />
            </div>
          )}
        </fieldset>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="flex justify-end">
        <Button
          variant="outline"
          ignoreTitleCase
          disabled={readOnly || !dirty || !draftValid(draft) || patch.isPending}
          onClick={save}
        >
          {patch.isPending ? "Saving…" : `Save ${dataset.source_index}`}
        </Button>
      </div>
    </section>
  );
}

interface MappingStepProps {
  imp: SnapshotImport;
  onDone: () => void;
}

export function MappingStep({ imp, onDone }: MappingStepProps) {
  const activate = useActivateSnapshotImport();
  const [edits, setEdits] = useState<Record<string, DatasetDraft>>({});
  const isActive = imp.status === "active";
  const readOnly = !imp.is_owner;

  const draftFor = (dataset: SnapshotDataset) =>
    edits[dataset.id] ?? draftFromDataset(dataset);
  const anyDirty = imp.datasets.some(
    (dataset) =>
      JSON.stringify(draftFor(dataset)) !==
      JSON.stringify(draftFromDataset(dataset)),
  );

  const activateImport = async () => {
    try {
      await activate.mutateAsync(imp.id);
      toast.success(`${imp.name} is active`);
    } catch {
      // Rendered below from `activate.error`.
    }
  };

  const activateError = activate.error;
  const roleJson =
    activateError instanceof SnapshotApiError &&
    activateError.code === "role_not_provisioned"
      ? (activateError.roleJson ?? imp.role_json ?? {})
      : null;

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        {isActive
          ? "This import is active and searchable. You can still adjust how each dataset is searched."
          : "Choose how each dataset is searched, then activate the import to make it searchable from chat, search and MCP."}
      </p>

      {imp.datasets.map((dataset) => (
        <DatasetForm
          key={dataset.id}
          importId={imp.id}
          dataset={dataset}
          draft={draftFor(dataset)}
          readOnly={readOnly}
          onDraftChange={(draft) =>
            setEdits((current) => ({ ...current, [dataset.id]: draft }))
          }
          onSaved={(submitted, saved) =>
            // Adopt the server's canonical (e.g. trimmed) values, unless the
            // user kept editing while the request was in flight.
            setEdits((current) =>
              JSON.stringify(current[dataset.id]) === JSON.stringify(submitted)
                ? { ...current, [dataset.id]: draftFromDataset(saved) }
                : current,
            )
          }
        />
      ))}

      {roleJson ? (
        <Alert variant="destructive">
          <AlertTitle>Role not provisioned</AlertTitle>
          <AlertDescription className="space-y-2">
            <p>
              OpenRAG does not manage OpenSearch security on this deployment.
              Create this role and mapping in OpenSearch, then activate again.
            </p>
            <pre
              aria-label="Role JSON"
              className="max-h-64 overflow-auto rounded bg-muted p-3 font-mono text-xs text-foreground"
            >
              {JSON.stringify(roleJson, null, 2)}
            </pre>
          </AlertDescription>
        </Alert>
      ) : (
        activateError && (
          <Alert variant="destructive">
            <AlertDescription>{activateError.message}</AlertDescription>
          </Alert>
        )
      )}

      <div className="flex items-center justify-end gap-2">
        {anyDirty && !isActive && (
          <span className="text-xs text-muted-foreground">
            Save your changes before activating.
          </span>
        )}
        {isActive ? (
          <Button onClick={onDone}>Done</Button>
        ) : (
          <Button
            disabled={readOnly || anyDirty || activate.isPending}
            onClick={activateImport}
          >
            {activate.isPending ? "Activating…" : "Activate"}
          </Button>
        )}
      </div>
    </div>
  );
}
