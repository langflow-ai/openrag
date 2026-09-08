"use client";

import Image from "next/image";
import { type ReactNode, useLayoutEffect, useMemo, useRef } from "react";
import type {
  DoclingPictureItem,
  DoclingTableItem,
  DoclingTextItem,
  ParsedItem,
} from "./types";
import {
  collectParsedItems,
  groupPreviewItems,
  itemMatchesHighlight,
  LABEL_NAMES,
  MAX_TEXT_PREVIEW_ITEMS,
  scrollNodeIntoPane,
} from "./utils";

function ParsedBlock({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="relative rounded-md border-2 border-dashed border-blue-600/70 bg-blue-600/[0.12] px-3 pt-4 pb-2 dark:border-blue-500 dark:bg-blue-500/15">
      <span className="absolute -top-2 left-2 rounded px-1 py-px text-xxs font-medium uppercase leading-none tracking-wide bg-blue-600 text-white dark:bg-blue-500">
        {label}
      </span>
      {children}
    </div>
  );
}

function DoclingTextLine({ item }: { item: DoclingTextItem }) {
  const text = item.text?.trim();
  if (!text) {
    return null;
  }
  const label = item.label ?? "text";
  const textClass =
    label === "title"
      ? "text-sm font-bold text-foreground"
      : label === "section_header"
        ? "text-sm font-semibold text-foreground"
        : label === "list_item"
          ? "pl-2 text-xs text-foreground"
          : "text-xs text-foreground";
  return (
    <ParsedBlock label={LABEL_NAMES[label] ?? "Text"}>
      <p className={textClass}>{label === "list_item" ? `• ${text}` : text}</p>
    </ParsedBlock>
  );
}

function DoclingTableBlock({ table }: { table: DoclingTableItem }) {
  const grid = table.data?.grid;
  if (!Array.isArray(grid) || grid.length === 0) {
    return null;
  }
  return (
    <ParsedBlock label="Table">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xxs">
          <tbody>
            {grid.map((row, rowIndex) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: parsed grid is static
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td
                    // biome-ignore lint/suspicious/noArrayIndexKey: parsed grid is static
                    key={cellIndex}
                    className="border border-border/40 px-2 py-1 align-top text-foreground"
                  >
                    {cell?.text ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ParsedBlock>
  );
}

function DoclingPictureBlock({ picture }: { picture: DoclingPictureItem }) {
  const uri = picture.image?.uri;
  if (!uri) {
    return (
      <ParsedBlock label="Figure">
        <p className="text-xxs text-muted-foreground">
          Figure detected (image not embedded).
        </p>
      </ParsedBlock>
    );
  }
  return (
    <ParsedBlock label="Figure">
      <Image
        src={uri}
        alt="Parsed figure"
        width={640}
        height={360}
        unoptimized
        className="max-h-48 h-auto w-auto rounded border border-border/40 bg-background object-contain"
      />
    </ParsedBlock>
  );
}

function renderParsedItem(item: ParsedItem) {
  if (item.kind === "table") {
    return <DoclingTableBlock key={item.id} table={item.node} />;
  }
  if (item.kind === "picture") {
    return <DoclingPictureBlock key={item.id} picture={item.node} />;
  }
  return <DoclingTextLine key={item.id} item={item.node} />;
}

/**
 * Renders the parsed structure for formats that have no page rasters (docx,
 * pptx, xlsx, html, csv, md, …). Type annotations stay visible; a selected
 * chunk adds an outer Chunk N frame around matched regions.
 */
export function DoclingTextPreview({
  doclingDocument,
  highlightItemRefs,
  highlightText,
  chunkLabel,
}: {
  doclingDocument: Record<string, unknown>;
  highlightItemRefs?: string[];
  highlightText?: string;
  chunkLabel?: string;
}) {
  // Fetch one extra item so we can show a "more regions" hint without walking
  // the entire Docling tree for huge office docs.
  const items = useMemo(
    () => collectParsedItems(doclingDocument, MAX_TEXT_PREVIEW_ITEMS + 1),
    [doclingDocument],
  );
  const truncated = items.length > MAX_TEXT_PREVIEW_ITEMS;
  const visible = useMemo(
    () => (truncated ? items.slice(0, MAX_TEXT_PREVIEW_ITEMS) : items),
    [items, truncated],
  );

  const groups = useMemo(() => {
    if (!chunkLabel) {
      return visible.map((item) => ({ kind: "plain" as const, item }));
    }
    return groupPreviewItems(visible, (item) =>
      itemMatchesHighlight(item, highlightItemRefs, highlightText),
    );
  }, [visible, chunkLabel, highlightItemRefs, highlightText]);

  const chunkFrameRef = useRef<HTMLDivElement | null>(null);
  const highlightKey = `${chunkLabel ?? ""}:${(highlightItemRefs ?? []).join(",")}:${highlightText ?? ""}`;
  const firstChunkKey = useMemo(() => {
    const first = groups.find((group) => group.kind === "chunk");
    return first?.kind === "chunk"
      ? first.items.map((item) => item.id).join("|")
      : null;
  }, [groups]);

  useLayoutEffect(() => {
    if (!chunkLabel || !firstChunkKey) return;
    // Re-run when highlight refs/text change under the same chunk label.
    void highlightKey;
    const raf = window.requestAnimationFrame(() => {
      scrollNodeIntoPane(chunkFrameRef.current);
    });
    return () => window.cancelAnimationFrame(raf);
  }, [highlightKey, chunkLabel, firstChunkKey]);

  if (items.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center px-4 text-center text-xxs text-muted-foreground">
        Parsing finished, but no extractable text or tables were found in this
        document.
      </div>
    );
  }

  return (
    <div
      className="space-y-3 rounded-md border border-border/40 bg-white p-4 shadow-sm dark:bg-slate-900"
      data-testid="docling-text-preview"
    >
      {groups.map((group) => {
        if (group.kind === "plain") {
          return renderParsedItem(group.item);
        }
        const key = group.items.map((item) => item.id).join("|");
        return (
          <div
            key={key}
            ref={key === firstChunkKey ? chunkFrameRef : undefined}
            className="relative space-y-3 rounded-md border-2 border-dashed border-blue-700 bg-blue-700/[0.06] p-3 pt-5 dark:border-blue-400"
            data-testid="docling-text-chunk-frame"
          >
            <span className="absolute -top-2.5 left-2 rounded px-1.5 py-0.5 text-xxs font-medium uppercase leading-none tracking-wide bg-blue-700 text-white dark:bg-blue-400">
              {chunkLabel}
            </span>
            {group.items.map((item) => renderParsedItem(item))}
          </div>
        );
      })}
      {truncated && (
        <p className="text-xxs text-muted-foreground">
          Showing first {MAX_TEXT_PREVIEW_ITEMS} regions — more remain in the
          document
        </p>
      )}
    </div>
  );
}
