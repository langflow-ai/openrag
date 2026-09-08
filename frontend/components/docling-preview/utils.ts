import type {
  DoclingImgElement,
  DoclingImgPageElement,
  DoclingPictureItem,
  DoclingRef,
  DoclingTableItem,
  DoclingTextItem,
  LitUpdatable,
  OverlayBox,
  ParsedItem,
  PreviewGroup,
} from "./types";

/**
 * Hard deadline so a hung Lit update cannot stall chunk overlay placement.
 * Not a poll interval — raced once against updateComplete + one rAF.
 */
export const LIT_UPDATE_TIMEOUT_MS = 1000;

export const LAYOUT_BOX_STYLE =
  "stroke: rgb(37, 99, 235); stroke-width: 2px; fill: rgba(37, 99, 235, 0.12); fill-opacity: 1;";

/** Stronger dashed stroke for items that belong to the selected chunk. */
export const CHUNK_HIT_STYLE =
  "stroke: rgb(29, 78, 216); stroke-width: 3px; stroke-dasharray: 6 3; fill: rgba(37, 99, 235, 0.18); fill-opacity: 1;";

export const LABEL_NAMES: Record<string, string> = {
  title: "Title",
  section_header: "Heading",
  list_item: "List",
  caption: "Caption",
  page_header: "Header",
  page_footer: "Footer",
  footnote: "Footnote",
};

/** Cap DOM nodes for huge office docs (full set stays in the index on the right). */
export const MAX_TEXT_PREVIEW_ITEMS = 120;

let doclingComponentsLoaded: Promise<void> | null = null;

export function loadDoclingComponents(): Promise<void> {
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

export function itemSelfRef(item: unknown): string | undefined {
  if (!item || typeof item !== "object") return undefined;
  const ref = (item as { self_ref?: unknown }).self_ref;
  return typeof ref === "string" ? ref : undefined;
}

export function itemOnDoclingPage(item: unknown, pageNo: number): boolean {
  if (!item || typeof item !== "object") return false;
  const prov = (item as { prov?: Array<{ page_no?: number }> }).prov;
  if (!Array.isArray(prov) || prov.length === 0) return false;
  return prov.some((p) => p.page_no === pageNo);
}

export function pageNoOf(page: unknown): number | null {
  if (!page || typeof page !== "object") return null;
  const n = (page as { page_no?: unknown }).page_no;
  return typeof n === "number" ? n : null;
}

function isScrollableOverflowY(el: HTMLElement): boolean {
  const { overflowY } = getComputedStyle(el);
  return (
    overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay"
  );
}

export function findScrollParent(el: HTMLElement): HTMLElement | null {
  let node: HTMLElement | null = el.parentElement;
  let overflowCandidate: HTMLElement | null = null;
  while (node) {
    if (isScrollableOverflowY(node)) {
      // Prefer an ancestor that can actually scroll. Nested overflow-auto
      // frames (preview pane inside a dialog) often have no overflow while the
      // outer dialog does — scrolling the inner one is a silent no-op.
      if (node.scrollHeight > node.clientHeight + 1) {
        return node;
      }
      overflowCandidate ??= node;
    }
    node = node.parentElement;
  }
  return overflowCandidate;
}

function targetScrollTop(
  el: Element,
  scrollParent: HTMLElement,
  paddingPx: number,
): number | null {
  const parentRect = scrollParent.getBoundingClientRect();
  const elRect = el.getBoundingClientRect();
  if (elRect.width === 0 && elRect.height === 0) return null;
  return Math.max(
    0,
    elRect.top - parentRect.top + scrollParent.scrollTop - paddingPx,
  );
}

/**
 * Smooth-scroll the primary overflow container to `el`. Only one container is
 * animated — repeated scrollTo calls cancel the browser's smooth animation.
 */
export function scrollElementThroughAncestors(
  el: Element,
  preferredContainers: Array<HTMLElement | null | undefined>,
  paddingPx = 48,
) {
  const seen = new Set<HTMLElement>();
  const candidates: HTMLElement[] = [];
  for (const preferred of preferredContainers) {
    if (
      preferred &&
      preferred.scrollHeight > preferred.clientHeight + 1 &&
      !seen.has(preferred)
    ) {
      seen.add(preferred);
      candidates.push(preferred);
    }
  }

  let current: Element | null = el;
  while (current) {
    const parentNode: Node | null = current.parentNode;
    if (!parentNode) break;
    if (parentNode instanceof ShadowRoot) {
      current = parentNode.host;
      continue;
    }
    if (!(parentNode instanceof HTMLElement)) break;
    if (
      isScrollableOverflowY(parentNode) &&
      parentNode.scrollHeight > parentNode.clientHeight + 1 &&
      !seen.has(parentNode)
    ) {
      seen.add(parentNode);
      candidates.push(parentNode);
    }
    current = parentNode;
  }

  const primary = candidates[0];
  if (!primary) return;
  const top = targetScrollTop(el, primary, paddingPx);
  if (top == null) return;
  primary.scrollTo({ top, behavior: "smooth" });
}

export function listDoclingPageElements(
  viewer: DoclingImgElement,
): DoclingImgPageElement[] {
  const root = viewer.shadowRoot;
  if (!root) return [];
  return Array.from(
    root.querySelectorAll<DoclingImgPageElement>("docling-img-page"),
  );
}

export function findDoclingPageElement(
  viewer: DoclingImgElement,
  pageNo: number,
): DoclingImgPageElement | null {
  const pages = listDoclingPageElements(viewer);
  for (const pageEl of pages) {
    if (pageEl.page?.page_no === pageNo) return pageEl;
  }
  // Index fallback when Lit hasn't hydrated `.page` yet (1-based).
  return pages[pageNo - 1] ?? null;
}

function awaitLitUpdate(node: LitUpdatable): Promise<void> {
  return Promise.resolve(node.updateComplete).then(() => undefined);
}

function nextAnimationFrame(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => resolve());
  });
}

/**
 * Wait for the viewer and nested page Lit elements to finish updating, then
 * one animation frame so getBoundingClientRect reflects laid-out geometry.
 * Parent updateComplete does not wait for children by default.
 */
export async function waitForDoclingLitPaint(
  viewer: DoclingImgElement,
): Promise<void> {
  const pages = listDoclingPageElements(viewer);
  await Promise.all([
    awaitLitUpdate(viewer),
    ...pages.map((page) => awaitLitUpdate(page)),
  ]);
  await nextAnimationFrame();
}

/**
 * `docling-img-page` hosts have no :host display rule (default inline) and can
 * report a 0×0 box. Scroll/measure the inner `.page` / SVG instead.
 */
export function findDoclingPageAnchor(
  viewer: DoclingImgElement,
  pageNo: number,
): Element | null {
  const pageEl = findDoclingPageElement(viewer, pageNo);
  if (!pageEl) return null;
  const inner =
    pageEl.shadowRoot?.querySelector(".page") ??
    pageEl.shadowRoot?.querySelector("svg.base") ??
    pageEl.shadowRoot?.querySelector("svg") ??
    null;
  return inner ?? pageEl;
}

export function unionRect(
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

export function collectChunkHitElements(
  viewer: DoclingImgElement,
): SVGRectElement[] {
  const root = viewer.shadowRoot;
  if (!root) return [];

  const elements: SVGRectElement[] = [];
  // docling-img-page is a nested Lit element with its own shadow root; rects
  // live there, not on the parent docling-img shadow tree.
  const pages = listDoclingPageElements(viewer);
  if (pages.length > 0) {
    for (const page of pages) {
      const pageRoot = page.shadowRoot;
      if (!pageRoot) continue;
      for (const rect of pageRoot.querySelectorAll<SVGRectElement>(
        "rect[part~='chunk-hit']",
      )) {
        elements.push(rect);
      }
    }
    return elements;
  }

  for (const rect of root.querySelectorAll<SVGRectElement>(
    "rect[part~='chunk-hit']",
  )) {
    elements.push(rect);
  }
  return elements;
}

export function collectChunkHitRects(viewer: DoclingImgElement): DOMRect[] {
  return collectChunkHitElements(viewer).map((el) =>
    el.getBoundingClientRect(),
  );
}

/** Stable geometry fingerprint so we can detect when Lit cleared stale hits. */
export function hitRectsSignature(rects: DOMRect[]): string {
  if (rects.length === 0) return "";
  return rects
    .map(
      (r) =>
        `${Math.round(r.top)}:${Math.round(r.left)}:${Math.round(r.width)}:${Math.round(r.height)}`,
    )
    .join("|");
}

export function collectPageItemElements(
  viewer: DoclingImgElement,
  pageNo: number,
): SVGRectElement[] {
  const elements: SVGRectElement[] = [];
  for (const pageEl of listDoclingPageElements(viewer)) {
    const pageRoot = pageEl.shadowRoot;
    if (!pageRoot || pageEl.page?.page_no !== pageNo) continue;
    for (const rect of pageRoot.querySelectorAll<SVGRectElement>(
      "rect[part~='item']",
    )) {
      elements.push(rect);
    }
  }
  return elements;
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

/**
 * Walks the DoclingDocument body in reading order, resolving refs to texts,
 * tables, and pictures. Recurses through groups and through children nested
 * under text/table/picture nodes (common for HTML, where Docling nests body
 * content under title/section_header parents). Falls back to concatenating
 * the top-level arrays when no body ordering is present.
 * Stops once `limit` items are collected (used to cap the left-pane DOM).
 */
export function collectParsedItems(
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

export function itemMatchesHighlight(
  item: ParsedItem,
  highlightItemRefs: string[] | undefined,
  highlightText: string | undefined,
): boolean {
  // Refs win exclusively — also applying text OR creates a second "Chunk N"
  // frame on non-consecutive regions that share phrases.
  if (highlightItemRefs && highlightItemRefs.length > 0) {
    return highlightItemRefs.includes(item.id);
  }
  if (!highlightText?.trim()) return false;
  const needle = normalizeNeedle(highlightText);
  const hay = normalizeNeedle(parsedItemText(item));
  if (!hay) return false;
  return hay.includes(needle) || needle.includes(hay);
}

/** Collapse consecutive matched items into one outer Chunk N frame. */
export function groupPreviewItems(
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

export function scrollNodeIntoPane(node: HTMLElement | null) {
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
