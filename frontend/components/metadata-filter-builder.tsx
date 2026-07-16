"use client";

import { Plus, Trash2 } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type MetadataOperator =
  | "equals"
  | "not_equals"
  | "in"
  | "not_in"
  | "contains"
  | "not_contains"
  | "exists"
  | "not_exists"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "between";

export interface MetadataCondition {
  key: string;
  operator: MetadataOperator;
  value?: unknown;
}

export interface MetadataGroup {
  op: "and" | "or";
  conditions: Array<MetadataCondition | MetadataGroup>;
}

interface MetadataField {
  key: string;
  type: "string" | "number" | "date" | "boolean";
}

const isGroup = (
  item: MetadataCondition | MetadataGroup,
): item is MetadataGroup => "conditions" in item;

const operatorsFor = (type: MetadataField["type"] | undefined) => {
  const base: MetadataOperator[] = [
    "equals",
    "not_equals",
    "in",
    "not_in",
    "exists",
    "not_exists",
  ];
  if (type === "string") base.push("contains", "not_contains");
  if (type === "number" || type === "date") {
    base.push("gt", "gte", "lt", "lte", "between");
  }
  return base;
};

const scalarValue = (raw: string, type: MetadataField["type"] | undefined) =>
  type === "number" ? Number(raw) : type === "boolean" ? raw === "true" : raw;

function ConditionEditor({
  condition,
  fields,
  onChange,
  onRemove,
}: {
  condition: MetadataCondition;
  fields: MetadataField[];
  onChange: (condition: MetadataCondition) => void;
  onRemove: () => void;
}) {
  const field = fields.find((candidate) => candidate.key === condition.key);
  const valueListId = useId();
  const [suggestedValues, setSuggestedValues] = useState<unknown[]>([]);
  useEffect(() => {
    if (!condition.key) return;
    fetch(
      `/api/metadata/fields/${encodeURIComponent(condition.key)}/values?limit=50`,
    )
      .then((response) => (response.ok ? response.json() : { values: [] }))
      .then((result) =>
        setSuggestedValues(
          (result.values ?? []).map((item: { value: unknown }) => item.value),
        ),
      )
      .catch(() => undefined);
  }, [condition.key]);
  const noValue =
    condition.operator === "exists" || condition.operator === "not_exists";
  const isList = condition.operator === "in" || condition.operator === "not_in";
  const between = condition.operator === "between";
  const inputType =
    field?.type === "date"
      ? "date"
      : field?.type === "number"
        ? "number"
        : "text";

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_150px_minmax(0,1fr)_36px] gap-2">
      <Select
        value={condition.key}
        onValueChange={(key) =>
          onChange({ key, operator: "equals", value: "" })
        }
      >
        <SelectTrigger>
          <SelectValue placeholder="Metadata field" />
        </SelectTrigger>
        <SelectContent>
          {fields.map((item) => (
            <SelectItem key={item.key} value={item.key}>
              {item.key}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select
        value={condition.operator}
        onValueChange={(operator: MetadataOperator) =>
          onChange({
            ...condition,
            operator,
            value:
              operator === "between" ? { gte: "", lte: "" } : condition.value,
          })
        }
      >
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {operatorsFor(field?.type).map((operator) => (
            <SelectItem key={operator} value={operator}>
              {operator.replaceAll("_", " ")}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {noValue ? (
        <div />
      ) : between ? (
        <div className="flex gap-2">
          <Input
            aria-label="Lower bound"
            type={inputType}
            value={String((condition.value as { gte?: unknown })?.gte ?? "")}
            onChange={(event) =>
              onChange({
                ...condition,
                value: {
                  ...(condition.value as object),
                  gte: scalarValue(event.target.value, field?.type),
                },
              })
            }
          />
          <Input
            aria-label="Upper bound"
            type={inputType}
            value={String((condition.value as { lte?: unknown })?.lte ?? "")}
            onChange={(event) =>
              onChange({
                ...condition,
                value: {
                  ...(condition.value as object),
                  lte: scalarValue(event.target.value, field?.type),
                },
              })
            }
          />
        </div>
      ) : field?.type === "boolean" ? (
        <Select
          value={String(condition.value ?? false)}
          onValueChange={(value) =>
            onChange({ ...condition, value: value === "true" })
          }
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="true">True</SelectItem>
            <SelectItem value="false">False</SelectItem>
          </SelectContent>
        </Select>
      ) : (
        <>
          <datalist id={valueListId}>
            {suggestedValues.map((value) => (
              <option key={String(value)} value={String(value)} />
            ))}
          </datalist>
          <Input
            aria-label="Filter value"
            list={field?.type === "string" ? valueListId : undefined}
            placeholder={isList ? "value one, value two" : "Value"}
            type={isList ? "text" : inputType}
            value={
              Array.isArray(condition.value)
                ? condition.value.join(", ")
                : String(condition.value ?? "")
            }
            onChange={(event) =>
              onChange({
                ...condition,
                value: isList
                  ? event.target.value
                      .split(",")
                      .map((item) => scalarValue(item.trim(), field?.type))
                      .filter((item) => item !== "")
                  : scalarValue(event.target.value, field?.type),
              })
            }
          />
        </>
      )}
      <Button
        aria-label="Remove condition"
        onClick={onRemove}
        size="icon"
        type="button"
        variant="ghost"
      >
        <Trash2 className="h-4 w-4" />
      </Button>
    </div>
  );
}

function GroupEditor({
  group,
  fields,
  onChange,
  removable,
  onRemove,
}: {
  group: MetadataGroup;
  fields: MetadataField[];
  onChange: (group: MetadataGroup) => void;
  removable?: boolean;
  onRemove?: () => void;
}) {
  const replace = (index: number, item: MetadataCondition | MetadataGroup) => {
    const conditions = [...group.conditions];
    conditions[index] = item;
    onChange({ ...group, conditions });
  };
  return (
    <div className="space-y-3 rounded-lg border p-3">
      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground">Match</span>
        <Select
          value={group.op}
          onValueChange={(op: "and" | "or") => onChange({ ...group, op })}
        >
          <SelectTrigger className="w-24">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="and">All</SelectItem>
            <SelectItem value="or">Any</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-sm text-muted-foreground">conditions</span>
        {removable && (
          <Button
            className="ml-auto"
            onClick={onRemove}
            size="sm"
            type="button"
            variant="ghost"
          >
            Remove group
          </Button>
        )}
      </div>
      {group.conditions.map((item, index) =>
        isGroup(item) ? (
          <GroupEditor
            fields={fields}
            group={item}
            // biome-ignore lint/suspicious/noArrayIndexKey: expression nodes have no persisted UI identifier
            key={index}
            onChange={(next) => replace(index, next)}
            onRemove={() =>
              onChange({
                ...group,
                conditions: group.conditions.filter(
                  (_, current) => current !== index,
                ),
              })
            }
            removable
          />
        ) : (
          <ConditionEditor
            condition={item}
            fields={fields}
            // biome-ignore lint/suspicious/noArrayIndexKey: expression nodes have no persisted UI identifier
            key={index}
            onChange={(next) => replace(index, next)}
            onRemove={() =>
              onChange({
                ...group,
                conditions: group.conditions.filter(
                  (_, current) => current !== index,
                ),
              })
            }
          />
        ),
      )}
      <div className="flex gap-2">
        <Button
          disabled={!fields.length}
          onClick={() =>
            onChange({
              ...group,
              conditions: [
                ...group.conditions,
                { key: fields[0]?.key ?? "", operator: "equals", value: "" },
              ],
            })
          }
          size="sm"
          type="button"
          variant="outline"
        >
          <Plus className="h-4 w-4" /> Condition
        </Button>
        <Button
          onClick={() =>
            onChange({
              ...group,
              conditions: [...group.conditions, { op: "and", conditions: [] }],
            })
          }
          size="sm"
          type="button"
          variant="outline"
        >
          <Plus className="h-4 w-4" /> Group
        </Button>
      </div>
    </div>
  );
}

export function MetadataFilterBuilder({
  value,
  onChange,
}: {
  value?: MetadataGroup;
  onChange: (value: MetadataGroup | undefined) => void;
}) {
  const [fields, setFields] = useState<MetadataField[]>([]);
  useEffect(() => {
    fetch("/api/metadata/fields")
      .then((response) => (response.ok ? response.json() : { fields: [] }))
      .then((result) =>
        setFields(
          (result.fields ?? []).filter((field: MetadataField) => !!field.type),
        ),
      )
      .catch(() => undefined);
  }, []);

  if (!value) {
    return (
      <Button
        disabled={!fields.length}
        onClick={() => onChange({ op: "and", conditions: [] })}
        size="sm"
        type="button"
        variant="outline"
      >
        <Plus className="h-4 w-4" /> Add metadata filters
      </Button>
    );
  }
  return (
    <div className="space-y-2">
      <GroupEditor fields={fields} group={value} onChange={onChange} />
      <Button
        onClick={() => onChange(undefined)}
        size="sm"
        type="button"
        variant="ghost"
      >
        Clear metadata filters
      </Button>
    </div>
  );
}
