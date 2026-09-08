"use client";

import {
  type RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { DoclingImgElement, DoclingImgPageElement } from "./types";
import { useChunkHighlightOverlay } from "./use-chunk-highlight-overlay";
import {
  CHUNK_HIT_STYLE,
  itemOnDoclingPage,
  itemSelfRef,
  LAYOUT_BOX_STYLE,
  loadDoclingComponents,
  pageNoOf,
} from "./utils";

export function DoclingParseViewer({
  doclingDocument,
  highlightItemRefs,
  fallbackPage,
  chunkLabel,
  scrollContainerRef,
}: {
  doclingDocument: Record<string, unknown>;
  /** Matched Docling self_refs — styled in-place; all other annotations stay. */
  highlightItemRefs?: string[];
  /** When no item refs matched, emphasize every item on this 1-based Docling page. */
  fallbackPage?: number | null;
  /** e.g. "Chunk 5" — chip on the outer chunk border. */
  chunkLabel?: string;
  /** Preview frame with overflow — preferred scrollport for chunk jumps. */
  scrollContainerRef?: RefObject<HTMLElement | null>;
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
  // Fingerprint content so React identity churn does not reassign `src`
  // (re-rasterize resets scroll mid-selection).
  const documentIdentity = useMemo(() => {
    const pages = doclingDocument.pages;
    const pageCount = Array.isArray(pages)
      ? pages.length
      : pages && typeof pages === "object"
        ? Object.keys(pages).length
        : 0;
    const texts = Array.isArray(doclingDocument.texts)
      ? doclingDocument.texts.length
      : 0;
    const tables = Array.isArray(doclingDocument.tables)
      ? doclingDocument.tables.length
      : 0;
    return `${pageCount}:${texts}:${tables}`;
  }, [doclingDocument]);
  const documentIdentityRef = useRef<string>("");

  const isChunkHit = useCallback((page: unknown, item: unknown): boolean => {
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
  }, []);

  const applyChunkStyles = useCallback(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const partFn = (page: unknown, item: unknown) =>
      isChunkHit(page, item) ? "chunk-hit" : "";
    const styleFn = (page: unknown, item: unknown) =>
      isChunkHit(page, item) ? CHUNK_HIT_STYLE : LAYOUT_BOX_STYLE;
    viewer.itemPart = partFn;
    viewer.itemStyle = styleFn;
    viewer.requestUpdate?.();

    const pages =
      viewer.shadowRoot?.querySelectorAll<DoclingImgPageElement>(
        "docling-img-page",
      );
    pages?.forEach((page) => {
      page.itemPart = partFn;
      page.itemStyle = styleFn;
      page.requestUpdate?.();
    });
  }, [isChunkHit]);

  const overlay = useChunkHighlightOverlay({
    ready,
    hostRef,
    viewerRef,
    scrollContainerRef,
    chunkLabel,
    highlightKey,
    fallbackPage,
    applyStyles: applyChunkStyles,
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
      documentIdentityRef.current = "";
    }

    const viewer = viewerRef.current;
    // Never filter via `items` — that hides other layout annotations.
    viewer.items = undefined;
    viewer.removeAttribute("items");
    applyChunkStyles();
    if (documentIdentityRef.current !== documentIdentity) {
      documentIdentityRef.current = documentIdentity;
      viewer.src = doclingDocument;
    }
  }, [ready, doclingDocument, documentIdentity, applyChunkStyles]);

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
