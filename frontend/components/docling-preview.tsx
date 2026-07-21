"use client";

import Image from "next/image";
import {
  type ReactNode,
  type RefObject,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { cn } from "@/lib/utils";

type DoclingImgElement = HTMLElement & {
  src?: Record<string, unknown> | string;
  items?: string | unknown[];
  trim?: string;
  itemStyle?: (page: unknown, item: unknown) => string;
  itemPart?: (page: unknown, item: unknown) => string;
};

const LAYOUT_BOX_STYLE =
  "stroke: rgb(37, 99, 235); stroke-width: 2px; fill: rgba(37, 99, 235, 0.12); fill-opacity: 1;";

/** Stronger dashed stroke for items that belong to the selected chunk. */
const CHUNK_HIT_STYLE =
  "stroke: rgb(29, 78, 216); stroke-width: 3px; stroke-dasharray: 6 3; fill: rgba(37, 99, 235, 0.18); fill-opacity: 1;";

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

type OverlayBox = { top: number; left: number; width: number; height: number };

function itemSelfRef(item: unknown): string | undefined {
  if (!item || typeof item !== "object") return undefined;
  const ref = (item as { self_ref?: unknown }).self_ref;
  return typeof ref === "string" ? ref : undefined;
}

function itemOnDoclingPage(item: unknown, pageNo: number): boolean {
  if (!item || typeof item !== "object") return false;
  const prov = (item as { prov?: Array<{ page_no?: number }> }).prov;
  if (!Array.isArray(prov) || prov.length === 0) return false;
  return prov.some((p) => p.page_no === pageNo);
}

function pageNoOf(page: unknown): number | null {
  if (!page || typeof page !== "object") return null;
  const n = (page as { page_no?: unknown }).page_no;
  return typeof n === "number" ? n : null;
}

function findScrollParent(el: HTMLElement): HTMLElement | null {
  let node: HTMLElement | null = el.parentElement;
  while (node) {
    const { overflowY } = getComputedStyle(node);
    if (
      overflowY === "auto" ||
      overflowY === "scroll" ||
      overflowY === "overlay"
    ) {
      return node;
    }
    node = node.parentElement;
  }
  return null;
}

function unionRect(
  rects: DOMRect[],
  hostRect: DOMRect,
  scrollTop: number,
  scrollLeft: number,
): OverlayBox | null {
  if (rects.length === 0) return null;
  let top = Number.POSITIVE_INFINITY;
  let left = Number.POSITIVE_INFINITY;
  let bottom = Number.NEGATIVE_INFINITY;
  let right = Number.NEGATIVE_INFINITY;
  for (const r of rects) {
    top = Math.min(top, r.top);
    left = Math.min(left, r.left);
    bottom = Math.max(bottom, r.bottom);
    right = Math.max(right, r.right);
  }
  return {
    top: top - hostRect.top + scrollTop,
    left: left - hostRect.left + scrollLeft,
    width: right - left,
    height: bottom - top,
  };
}

function collectChunkHitRects(viewer: DoclingImgElement): DOMRect[] {
  const root = viewer.shadowRoot;
  if (!root) return [];

  const rects: DOMRect[] = [];
  // docling-img-page is a nested Lit element with its own shadow root; rects
  // live there, not on the parent docling-img shadow tree.
  const pages = root.querySelectorAll<HTMLElement>("docling-img-page");
  if (pages.length > 0) {
    for (const page of pages) {
      const pageRoot = page.shadowRoot;
      if (!pageRoot) continue;
      for (const rect of pageRoot.querySelectorAll<SVGRectElement>(
        "rect[part~='chunk-hit']",
      )) {
        rects.push(rect.getBoundingClientRect());
      }
    }
    return rects;
  }

  for (const rect of root.querySelectorAll<SVGRectElement>(
    "rect[part~='chunk-hit']",
  )) {
    rects.push(rect.getBoundingClientRect());
  }
  return rects;
}

/** Collect every item rect on a given Docling page (1-based), nested shadows. */
function collectPageItemRects(
  viewer: DoclingImgElement,
  pageNo: number,
): DOMRect[] {
  const root = viewer.shadowRoot;
  if (!root) return [];
  const pages = root.querySelectorAll<HTMLElement>("docling-img-page");
  const rects: DOMRect[] = [];
  for (const pageEl of pages) {
    const pageRoot = pageEl.shadowRoot;
    const page = (pageEl as HTMLElement & { page?: { page_no?: number } }).page;
    if (!pageRoot || page?.page_no !== pageNo) continue;
    for (const rect of pageRoot.querySelectorAll<SVGRectElement>(
      "rect[part~='item']",
    )) {
      rects.push(rect.getBoundingClientRect());
    }
  }
  return rects;
}

/**
 * Positions the Chunk N HTML overlay over matched layout rects and scrolls the
 * document pane so the union is visible — without filtering docling-img items.
 */
function useChunkHighlightOverlay({
  ready,
  hostRef,
  viewerRef,
  chunkLabel,
  highlightKey,
  fallbackPage,
}: {
  ready: boolean;
  hostRef: RefObject<HTMLDivElement | null>;
  viewerRef: RefObject<DoclingImgElement | null>;
  chunkLabel?: string;
  highlightKey: string;
  fallbackPage?: number | null;
}) {
  const [overlay, setOverlay] = useState<OverlayBox | null>(null);

  useLayoutEffect(() => {
    if (!ready || !chunkLabel) {
      setOverlay(null);
      return;
    }

    const host = hostRef.current;
    const viewer = viewerRef.current;
    if (!host || !viewer) return;

    let cancelled = false;
    let attempts = 0;
    const timers: number[] = [];
    const schedule = (fn: () => void, ms: number) => {
      timers.push(window.setTimeout(fn, ms));
    };

    const place = () => {
      if (cancelled) return;
      let hitRects = collectChunkHitRects(viewer);
      // If itemPart styling hasn't painted yet (or refs missed), fall back to
      // every layout box on the chunk's page so PDF still gets a Chunk N frame.
      if (
        hitRects.length === 0 &&
        typeof fallbackPage === "number" &&
        attempts >= 4
      ) {
        hitRects = collectPageItemRects(viewer, fallbackPage);
      }
      if (hitRects.length === 0) {
        attempts += 1;
        if (attempts < 20) {
          schedule(place, 50);
        } else {
          setOverlay(null);
        }
        return;
      }

      const hostRect = host.getBoundingClientRect();
      const box = unionRect(
        hitRects,
        hostRect,
        host.scrollTop,
        host.scrollLeft,
      );
      setOverlay(box);

      const scrollParent = findScrollParent(host);
      if (scrollParent && box) {
        const parentRect = scrollParent.getBoundingClientRect();
        const unionTopInParent =
          hitRects.reduce((min, r) => Math.min(min, r.top), hitRects[0].top) -
          parentRect.top +
          scrollParent.scrollTop;
        const target =
          unionTopInParent -
          Math.max(24, (scrollParent.clientHeight - box.height) / 3);
        scrollParent.scrollTo({
          top: Math.max(0, target),
          behavior: "smooth",
        });
      }
    };

    schedule(place, 50);
    return () => {
      cancelled = true;
      for (const timer of timers) {
        window.clearTimeout(timer);
      }
    };
  }, [ready, chunkLabel, highlightKey, fallbackPage, hostRef, viewerRef]);

  return overlay;
}

export function DoclingParseViewer({
  doclingDocument,
  highlightItemRefs,
  fallbackPage,
  chunkLabel,
}: {
  doclingDocument: Record<string, unknown>;
  /** Matched Docling self_refs — styled in-place; all other annotations stay. */
  highlightItemRefs?: string[];
  /** When no item refs matched, emphasize every item on this 1-based Docling page. */
  fallbackPage?: number | null;
  /** e.g. "Chunk 5" — chip on the outer chunk border. */
  chunkLabel?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<DoclingImgElement | null>(null);
  const matchedRefsRef = useRef<Set<string> | null>(null);
  const fallbackPageRef = useRef<number | null>(null);
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState(false);

  matchedRefsRef.current = new Set(highlightItemRefs ?? []);
  fallbackPageRef.current =
    typeof fallbackPage === "number" ? fallbackPage : null;

  const highlightKey = `${chunkLabel ?? ""}:${(highlightItemRefs ?? []).join(",")}:${fallbackPage ?? ""}`;

  const overlay = useChunkHighlightOverlay({
    ready,
    hostRef,
    viewerRef,
    chunkLabel,
    highlightKey,
    fallbackPage,
  });

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

  const isChunkHit = (page: unknown, item: unknown): boolean => {
    const refs = matchedRefsRef.current;
    if (refs && refs.size > 0) {
      const ref = itemSelfRef(item);
      return Boolean(ref && refs.has(ref));
    }
    const pageNo = fallbackPageRef.current;
    if (pageNo == null) return false;
    const fromItem = itemOnDoclingPage(item, pageNo);
    if (fromItem) return true;
    // Some items lack prov — fall back to the rendered page's page_no.
    return pageNoOf(page) === pageNo;
  };

  // Assigning `src` re-rasterizes embedded page images — only when the document
  // identity changes. Chunk emphasis goes through itemPart/itemStyle.
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
      container.appendChild(viewer);
      viewerRef.current = viewer;
    }

    const viewer = viewerRef.current;
    // Never filter via `items` — that hides other layout annotations.
    viewer.items = undefined;
    viewer.removeAttribute("items");
    viewer.itemPart = (page, item) =>
      isChunkHit(page, item) ? "chunk-hit" : "";
    viewer.itemStyle = (page, item) =>
      isChunkHit(page, item) ? CHUNK_HIT_STYLE : LAYOUT_BOX_STYLE;
    viewer.src = doclingDocument;
  }, [ready, doclingDocument]);

  // Re-apply hit styling when the selected chunk changes without reloading src.
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!ready || !viewer) return;
    const partFn = (page: unknown, item: unknown) =>
      isChunkHit(page, item) ? "chunk-hit" : "";
    const styleFn = (page: unknown, item: unknown) =>
      isChunkHit(page, item) ? CHUNK_HIT_STYLE : LAYOUT_BOX_STYLE;
    viewer.itemPart = partFn;
    viewer.itemStyle = styleFn;
    const lit = viewer as DoclingImgElement & { requestUpdate?: () => void };
    lit.requestUpdate?.();

    // Nested page elements keep their own reactive props — push updates down
    // so PDF overlays re-paint without a full src reload.
    const pages = viewer.shadowRoot?.querySelectorAll<
      HTMLElement & {
        itemPart?: typeof partFn;
        itemStyle?: typeof styleFn;
        requestUpdate?: () => void;
      }
    >("docling-img-page");
    pages?.forEach((page) => {
      page.itemPart = partFn;
      page.itemStyle = styleFn;
      page.requestUpdate?.();
    });
  }, [ready, highlightKey]);

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

  return (
    <div ref={hostRef} className="relative" data-testid="docling-parse-viewer">
      {/* Imperative docling-img mount point — keep empty of React children. */}
      <div ref={containerRef} />
      {overlay && chunkLabel ? (
        <div
          className="pointer-events-none absolute z-10 rounded-md border-2 border-dashed border-blue-700 dark:border-blue-400"
          style={{
            top: overlay.top,
            left: overlay.left,
            width: overlay.width,
            height: overlay.height,
          }}
          data-testid="docling-chunk-overlay"
        >
          <span
            className="absolute -top-2.5 left-2 rounded px-1.5 py-0.5 text-xxs font-medium uppercase leading-none tracking-wide bg-blue-700 text-white dark:bg-blue-400"
            data-testid="docling-chunk-label"
          >
            {chunkLabel}
          </span>
        </div>
      ) : null}
    </div>
  );
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

// Non-paged analog of LAYOUT_BOX_STYLE (pdf/docling-img overlays): same blue
// stroke + light fill, dashed frame so it matches across file types.
const LABEL_NAMES: Record<string, string> = {
  title: "Title",
  section_header: "Heading",
  list_item: "List",
  caption: "Caption",
  page_header: "Header",
  page_footer: "Footer",
  footnote: "Footnote",
};

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
 * tables, and pictures. Recurses through groups and through children nested
 * under text/table/picture nodes (common for HTML, where Docling nests body
 * content under title/section_header parents). Falls back to concatenating
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
        // HTML Docling trees nest following content under heading nodes.
        walk(node.children);
      } else if (path.startsWith("#/tables")) {
        result.push({ kind: "table", id: path, node });
        walk(node.children);
      } else if (path.startsWith("#/pictures")) {
        result.push({ kind: "picture", id: path, node });
        walk(node.children);
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

function normalizeNeedle(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function parsedItemText(item: ParsedItem): string {
  if (item.kind === "text") return item.node.text ?? "";
  if (item.kind === "table") {
    const grid = item.node.data?.grid;
    if (!Array.isArray(grid)) return "";
    return grid.flatMap((row) => row.map((cell) => cell?.text ?? "")).join(" ");
  }
  return "";
}

function itemMatchesHighlight(
  item: ParsedItem,
  highlightItemRefs: string[] | undefined,
  highlightText: string | undefined,
): boolean {
  if (highlightItemRefs?.includes(item.id)) return true;
  if (!highlightText?.trim()) return false;
  const needle = normalizeNeedle(highlightText);
  const hay = normalizeNeedle(parsedItemText(item));
  if (!hay) return false;
  return hay.includes(needle) || needle.includes(hay);
}

type PreviewGroup =
  | { kind: "chunk"; items: ParsedItem[] }
  | { kind: "plain"; item: ParsedItem };

/** Collapse consecutive matched items into one outer Chunk N frame. */
function groupPreviewItems(
  items: ParsedItem[],
  isHit: (item: ParsedItem) => boolean,
): PreviewGroup[] {
  const groups: PreviewGroup[] = [];
  for (const item of items) {
    if (isHit(item)) {
      const last = groups[groups.length - 1];
      if (last?.kind === "chunk") {
        last.items.push(item);
      } else {
        groups.push({ kind: "chunk", items: [item] });
      }
    } else {
      groups.push({ kind: "plain", item });
    }
  }
  return groups;
}

function scrollNodeIntoPane(node: HTMLElement | null) {
  if (!node) return;
  const scrollParent = findScrollParent(node);
  if (!scrollParent) {
    node.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return;
  }
  const parentRect = scrollParent.getBoundingClientRect();
  const nodeRect = node.getBoundingClientRect();
  const top = nodeRect.top - parentRect.top + scrollParent.scrollTop - 24;
  scrollParent.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
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
    if (!chunkLabel) return;
    scrollNodeIntoPane(chunkFrameRef.current);
  }, [highlightKey, chunkLabel]);

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
