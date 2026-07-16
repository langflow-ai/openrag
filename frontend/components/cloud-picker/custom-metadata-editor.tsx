"use client";

import { Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { CustomMetadataEntry, CustomMetadataType } from "./types";

interface MetadataFieldSuggestion {
  key: string;
  type: CustomMetadataType;
}

interface Props {
  value: CustomMetadataEntry[];
  onChange: (value: CustomMetadataEntry[]) => void;
}

const defaultValue = (type: CustomMetadataType): string | number | boolean => {
  if (type === "number") return 0;
  if (type === "boolean") return false;
  return "";
};

export function CustomMetadataEditor({ value, onChange }: Props) {
  const [suggestions, setSuggestions] = useState<MetadataFieldSuggestion[]>([]);

  useEffect(() => {
    let active = true;
    fetch("/api/metadata/fields")
      .then((response) => (response.ok ? response.json() : { fields: [] }))
      .then((result) => {
        if (active) setSuggestions(result.fields ?? []);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  const fieldTypes = useMemo(
    () => new Map(suggestions.map((field) => [field.key, field.type])),
    [suggestions],
  );

  const update = (index: number, patch: Partial<CustomMetadataEntry>) => {
    const next = [...value];
    next[index] = { ...next[index], ...patch };
    onChange(next);
  };

  return (
    <div className="mt-6 space-y-3 border-t pt-4">
      <div>
        <div className="text-sm font-semibold">Custom metadata</div>
        <div className="text-sm text-muted-foreground">
          Applied to every document selected for this ingest.
        </div>
      </div>
      <datalist id="custom-metadata-keys">
        {suggestions.map((field) => (
          <option key={field.key} value={field.key} />
        ))}
      </datalist>
      {value.map((entry, index) => {
        const knownType = fieldTypes.get(entry.key.trim().toLowerCase());
        return (
          <div
            className="grid grid-cols-[minmax(0,1fr)_130px_minmax(0,1fr)_36px] gap-2"
            key={`${index}-${entry.key}`}
          >
            <Input
              aria-label="Metadata key"
              list="custom-metadata-keys"
              placeholder="supplier"
              value={entry.key}
              onChange={(event) => {
                const key = event.target.value.toLowerCase();
                const suggestedType = fieldTypes.get(key);
                update(index, {
                  key,
                  ...(suggestedType && suggestedType !== entry.type
                    ? {
                        type: suggestedType,
                        value: defaultValue(suggestedType),
                      }
                    : {}),
                });
              }}
            />
            <Select
              disabled={!!knownType}
              value={knownType ?? entry.type}
              onValueChange={(type: CustomMetadataType) =>
                update(index, { type, value: defaultValue(type) })
              }
            >
              <SelectTrigger aria-label="Metadata type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="string">Text</SelectItem>
                <SelectItem value="number">Number</SelectItem>
                <SelectItem value="date">Date</SelectItem>
                <SelectItem value="boolean">Boolean</SelectItem>
              </SelectContent>
            </Select>
            {entry.type === "boolean" ? (
              <Select
                value={String(entry.value)}
                onValueChange={(next) =>
                  update(index, { value: next === "true" })
                }
              >
                <SelectTrigger aria-label="Metadata value">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="true">True</SelectItem>
                  <SelectItem value="false">False</SelectItem>
                </SelectContent>
              </Select>
            ) : (
              <Input
                aria-label="Metadata value"
                type={
                  entry.type === "date"
                    ? "date"
                    : entry.type === "number"
                      ? "number"
                      : "text"
                }
                value={String(entry.value)}
                onChange={(event) =>
                  update(index, {
                    value:
                      entry.type === "number"
                        ? Number(event.target.value)
                        : event.target.value,
                  })
                }
              />
            )}
            <Button
              aria-label="Remove metadata"
              onClick={() =>
                onChange(value.filter((_, itemIndex) => itemIndex !== index))
              }
              size="icon"
              type="button"
              variant="ghost"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        );
      })}
      <Button
        onClick={() =>
          onChange([...value, { key: "", type: "string", value: "" }])
        }
        size="sm"
        type="button"
        variant="outline"
      >
        <Plus className="h-4 w-4" /> Add metadata
      </Button>
    </div>
  );
}
