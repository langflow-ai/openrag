"use client";

import Image from "next/image";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";

type DoclingImgElement = HTMLElement & {
  src?: Record<string, unknown> | string;
  items?: string | unknown[];
  trim?: string;
  itemStyle?: (page: unknown, item: unknown) => string;
};

const LAYOUT_BOX_STYLE = () =>
  "stroke: rgb(37, 99, 235); stroke-width: 2px; fill: rgba(37, 99, 235, 0.12); fill-opacity: 1;";

let doclingComponentsLoaded: Promise<void> | null = null;

function loadDoclingComponents(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.resolve();
  }
  if (!doclingComponentsLoaded) {
    doclingComponentsLoaded = import("@docling/docling-components")
      .then(() => undefined)
      .catch((error) => {
        // Clear so a later mount can retry the dynamic import.
        doclingComponentsLoaded = null;
        throw error;
      });
  }
  return doclingComponentsLoaded;
}

export function DoclingParseViewer({
  doclingDocument,
  highlightItems,
}: {
  doclingDocument: Record<string, unknown>;
  highlightItems?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<DoclingImgElement | null>(null);
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void loadDoclingComponents()
      .then(() => {
        if (cancelled) return;
        setLoadError(false);
        setReady(true);
      })
      .catch(() => {
        if (cancelled) return;
        setReady(false);
        setLoadError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Assigning `src` re-rasterizes embedded page images — only when the document
  // identity changes. Highlight updates go through `items` alone.
  useEffect(() => {
    if (!ready || !containerRef.current) {
      return;
    }

    const container = containerRef.current;
    if (!viewerRef.current || !container.contains(viewerRef.current)) {
      container.replaceChildren();
      const viewer = document.createElement("docling-img") as DoclingImgElement;
      viewer.setAttribute("pagenumbers", "");
      viewer.trim = "";
      viewer.itemStyle = LAYOUT_BOX_STYLE;
      container.appendChild(viewer);
      viewerRef.current = viewer;
    }

    const viewer = viewerRef.current;
    viewer.itemStyle = LAYOUT_BOX_STYLE;
    viewer.src = doclingDocument;
  }, [ready, doclingDocument]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!ready || !viewer) {
      return;
    }
    if (highlightItems) {
      viewer.items = highlightItems;
    } else {
      viewer.items = undefined;
      viewer.removeAttribute("items");
    }
  }, [ready, highlightItems]);

  if (loadError) {
    return (
      <div
        className="flex h-40 items-center justify-center px-4 text-center text-xs text-muted-foreground"
        data-testid="docling-parse-viewer-error"
      >
        Document preview failed to load. Try again in a moment.
      </div>
    );
  }

  return <div ref={containerRef} data-testid="docling-parse-viewer" />;
}

type DoclingTextItem = {
  text?: string;
  label?: string;
  level?: number;
};

type DoclingTableCell = { text?: string };

type DoclingTableItem = {
  data?: { grid?: DoclingTableCell[][] };
};

type DoclingPictureItem = {
  image?: { uri?: string };
  captions?: unknown[];
};

type DoclingRef = { $ref?: string; cref?: string };

type BlockStyle = { name: string; border: string; chip: string };

// Type → bounding-box treatment. This is the non-paged analog of the docling-img
// layout boxes: since there's no page raster to overlay, we wrap each parsed
// region in its own colored, labeled box — same visual language, filled with the
// real content instead of drawn on a screenshot.
const LABEL_STYLES: Record<string, BlockStyle> = {
  title: {
    name: "Title",
    border: "border-indigo-500/70",
    chip: "bg-indigo-500 text-white",
  },
  section_header: {
    name: "Heading",
    border: "border-blue-500/70",
    chip: "bg-blue-500 text-white",
  },
  list_item: {
    name: "List",
    border: "border-amber-500/70",
    chip: "bg-amber-500 text-white",
  },
  caption: {
    name: "Caption",
    border: "border-slate-400/60",
    chip: "bg-slate-500 text-white",
  },
  page_header: {
    name: "Header",
    border: "border-slate-400/60",
    chip: "bg-slate-500 text-white",
  },
  page_footer: {
    name: "Footer",
    border: "border-slate-400/60",
    chip: "bg-slate-500 text-white",
  },
  footnote: {
    name: "Footnote",
    border: "border-slate-400/60",
    chip: "bg-slate-500 text-white",
  },
};

const DEFAULT_TEXT_STYLE: BlockStyle = {
  name: "Text",
  border: "border-sky-500/60",
  chip: "bg-sky-500 text-white",
};

const TABLE_STYLE: BlockStyle = {
  name: "Table",
  border: "border-emerald-500/70",
  chip: "bg-emerald-500 text-white",
};

const FIGURE_STYLE: BlockStyle = {
  name: "Figure",
  border: "border-purple-500/70",
  chip: "bg-purple-500 text-white",
};

function ParsedBlock({
  style,
  children,
}: {
  style: BlockStyle;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "relative rounded-md border-2 px-3 pt-4 pb-2",
        style.border,
      )}
    >
      <span
        className={cn(
          "absolute -top-2 left-2 rounded px-1 py-px text-xxs font-medium uppercase leading-none tracking-wide",
          style.chip,
        )}
      >
        {style.name}
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
  const style = LABEL_STYLES[label] ?? DEFAULT_TEXT_STYLE;
  const textClass =
    label === "title"
      ? "text-sm font-bold text-foreground"
      : label === "section_header"
        ? "text-sm font-semibold text-foreground"
        : label === "list_item"
          ? "pl-2 text-xs text-foreground"
          : "text-xs text-foreground";
  return (
    <ParsedBlock style={style}>
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
    <ParsedBlock style={TABLE_STYLE}>
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
      <ParsedBlock style={FIGURE_STYLE}>
        <p className="text-xxs text-muted-foreground">
          Figure detected (image not embedded).
        </p>
      </ParsedBlock>
    );
  }
  return (
    <ParsedBlock style={FIGURE_STYLE}>
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

function refPath(ref: DoclingRef | undefined): string | undefined {
  return ref?.$ref ?? ref?.cref;
}

function resolveRef(
  document: Record<string, unknown>,
  path: string,
): Record<string, unknown> | null {
  if (!path.startsWith("#/")) {
    return null;
  }
  let node: unknown = document;
  for (const part of path.slice(2).split("/")) {
    if (node == null) {
      return null;
    }
    node = Array.isArray(node)
      ? node[Number(part)]
      : (node as Record<string, unknown>)[part];
  }
  return (node as Record<string, unknown>) ?? null;
}

type ParsedItem =
  | { kind: "text"; id: string; node: DoclingTextItem }
  | { kind: "table"; id: string; node: DoclingTableItem }
  | { kind: "picture"; id: string; node: DoclingPictureItem };

/**
 * Walks the DoclingDocument body in reading order, resolving refs to texts,
 * tables, and pictures (recursing through groups). Falls back to concatenating
 * the top-level arrays when no body ordering is present.
 * Stops once `limit` items are collected (used to cap the left-pane DOM).
 */
function collectParsedItems(
  document: Record<string, unknown>,
  limit: number,
): ParsedItem[] {
  const result: ParsedItem[] = [];
  const seen = new Set<string>();

  const walk = (children: unknown): void => {
    if (!Array.isArray(children) || result.length >= limit) {
      return;
    }
    for (const ref of children) {
      if (result.length >= limit) return;
      const path = refPath(ref as DoclingRef);
      if (!path || seen.has(path)) {
        continue;
      }
      seen.add(path);
      const node = resolveRef(document, path);
      if (!node) {
        continue;
      }
      if (path.startsWith("#/texts")) {
        result.push({ kind: "text", id: path, node });
      } else if (path.startsWith("#/tables")) {
        result.push({ kind: "table", id: path, node });
      } else if (path.startsWith("#/pictures")) {
        result.push({ kind: "picture", id: path, node });
      } else if (path.startsWith("#/groups")) {
        walk(node.children);
      }
    }
  };

  const body = document.body as { children?: unknown } | undefined;
  walk(body?.children);

  if (result.length === 0) {
    const texts = (document.texts as DoclingTextItem[] | undefined) ?? [];
    for (let i = 0; i < texts.length; i += 1) {
      if (result.length >= limit) break;
      result.push({ kind: "text", id: `#/texts/${i}`, node: texts[i] });
    }
    const tables = (document.tables as DoclingTableItem[] | undefined) ?? [];
    for (let i = 0; i < tables.length; i += 1) {
      if (result.length >= limit) break;
      result.push({ kind: "table", id: `#/tables/${i}`, node: tables[i] });
    }
    const pictures =
      (document.pictures as DoclingPictureItem[] | undefined) ?? [];
    for (let i = 0; i < pictures.length; i += 1) {
      if (result.length >= limit) break;
      result.push({
        kind: "picture",
        id: `#/pictures/${i}`,
        node: pictures[i],
      });
    }
  }
  return result;
}

/** Cap DOM nodes for huge office docs (full set stays in the index on the right). */
const MAX_TEXT_PREVIEW_ITEMS = 120;

/**
 * Renders the parsed structure for formats that have no page rasters (docx,
 * pptx, xlsx, html, csv, md, …). The Docling web components
 * (`docling-img`/`docling-table`) are page-based and render blank without page
 * images, so we render the structured items from the DoclingDocument directly,
 * color-coded by the structure Docling classified — a visual indication of the
 * parse standing in for the layout boxes we can only draw on paged formats.
 */
export function DoclingTextPreview({
  doclingDocument,
}: {
  doclingDocument: Record<string, unknown>;
}) {
  // Fetch one extra item so we can show a "more regions" hint without walking
  // the entire Docling tree for huge office docs.
  const items = useMemo(
    () => collectParsedItems(doclingDocument, MAX_TEXT_PREVIEW_ITEMS + 1),
    [doclingDocument],
  );
  const truncated = items.length > MAX_TEXT_PREVIEW_ITEMS;
  const visible = truncated ? items.slice(0, MAX_TEXT_PREVIEW_ITEMS) : items;

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
      {visible.map((item) => {
        if (item.kind === "table") {
          return <DoclingTableBlock key={item.id} table={item.node} />;
        }
        if (item.kind === "picture") {
          return <DoclingPictureBlock key={item.id} picture={item.node} />;
        }
        return <DoclingTextLine key={item.id} item={item.node} />;
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
