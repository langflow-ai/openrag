"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export interface ChatScopeOption {
  value: string;
  label: string;
}

export type ChatScopePatch =
  | { data_sources: string[] }
  | { document_types: string[] };

function filenameSuggestions(
  sourceOptions: ChatScopeOption[],
  needle: string,
): ChatScopeOption[] {
  if (!needle) return [];
  const matched: ChatScopeOption[] = [];
  for (const option of sourceOptions) {
    if (option.value.toLowerCase().includes(needle)) {
      matched.push({ value: option.value, label: option.value });
    }
  }
  return matched;
}

interface ChatScopeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  query: string;
  /** Filenames already loaded for the sources menu. */
  sourceOptions: ChatScopeOption[];
  /** Document types the query names (`.txt`), already limited to indexed ones. */
  typeSuggestions: ChatScopeOption[];
  saving: boolean;
  onApply: (patch: ChatScopePatch) => void;
  onSaveTableOnly: () => void;
}

/**
 * Shown when a filter about to be saved restricts nothing chat can apply. It
 * offers the types or filenames the query matches, or a table-only save.
 *
 * Filenames come from the same list as the sources menu and are filtered the
 * same way, in the browser.
 */
export function ChatScopeDialog({
  open,
  onOpenChange,
  query,
  sourceOptions,
  typeSuggestions,
  saving,
  onApply,
  onSaveTableOnly,
}: ChatScopeDialogProps) {
  const trimmedQuery = query.trim();
  const needle = trimmedQuery.toLowerCase();
  const suggestsTypes = typeSuggestions.length > 0;

  const options: ChatScopeOption[] = suggestsTypes
    ? typeSuggestions
    : filenameSuggestions(sourceOptions, needle);

  const [deselected, setDeselected] = useState<Set<string>>(new Set());
  const [prevOptionsKey, setPrevOptionsKey] = useState("");
  const optionsKey = options.map((option) => option.value).join("\n");
  if (optionsKey !== prevOptionsKey) {
    setPrevOptionsKey(optionsKey);
    setDeselected(new Set());
  }

  const selected: string[] = [];
  for (const option of options) {
    if (!deselected.has(option.value)) selected.push(option.value);
  }

  const toggle = (value: string) => {
    setDeselected((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  };

  const handleApply = () => {
    onApply(
      suggestsTypes ? { document_types: selected } : { data_sources: selected },
    );
  };

  const hasSuggestion = options.length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>This filter won&apos;t apply in chat</DialogTitle>
          <DialogDescription>
            Chat only uses sources, types, owners, connectors and dates. The
            search query only filters the Knowledge table.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 text-sm">
          {hasSuggestion && (
            <>
              <p>
                {suggestsTypes
                  ? `Restrict chat to the type "${trimmedQuery}" refers to.`
                  : `${options.length} ${options.length === 1 ? "file matches" : "files match"} "${trimmedQuery}". Chat will use the ones you leave checked.`}
              </p>
              <ul className="max-h-48 space-y-2 overflow-y-auto rounded-md border p-3">
                {options.map((option) => {
                  const id = `chat-scope-${option.value}`;
                  return (
                    <li key={option.value} className="flex items-center gap-2">
                      <Checkbox
                        id={id}
                        checked={!deselected.has(option.value)}
                        onCheckedChange={() => toggle(option.value)}
                      />
                      <label htmlFor={id} className="truncate">
                        {option.label}
                      </label>
                    </li>
                  );
                })}
              </ul>
              <button
                type="button"
                className="text-left text-sm underline underline-offset-4 disabled:opacity-50"
                onClick={onSaveTableOnly}
                disabled={saving}
              >
                Save for Knowledge table only
              </button>
              <p className="text-xs text-muted-foreground">
                Chat will not use this filter. The search still runs on the
                Knowledge table.
              </p>
            </>
          )}

          {!hasSuggestion && (
            <p className="text-muted-foreground">
              {trimmedQuery
                ? `No files match "${trimmedQuery}". You can still keep this search on the Knowledge table.`
                : "Pick a source, type, owner, connector or date range to apply it in chat. You can still save it for the Knowledge table."}
            </p>
          )}
        </div>

        <div className="flex flex-wrap justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            ignoreTitleCase
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          {hasSuggestion ? (
            <Button
              type="button"
              ignoreTitleCase
              onClick={handleApply}
              disabled={saving || selected.length === 0}
            >
              Apply and save
            </Button>
          ) : (
            <Button
              type="button"
              ignoreTitleCase
              onClick={onSaveTableOnly}
              disabled={saving}
            >
              Save for Knowledge table only
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
