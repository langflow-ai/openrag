import { type RefObject, useLayoutEffect, useState } from "react";
import type { DoclingImgElement, OverlayBox } from "./types";
import {
  collectChunkHitElements,
  collectChunkHitRects,
  collectPageItemElements,
  findDoclingPageAnchor,
  findDoclingPageElement,
  findScrollParent,
  hitRectsSignature,
  LIT_UPDATE_TIMEOUT_MS,
  scrollElementThroughAncestors,
  unionRect,
  waitForDoclingLitPaint,
} from "./utils";

/**
 * Applies chunk hit styles, scrolls to the chunk's page, then places the
 * Chunk N overlay once geometry is fresh.
 *
 * Important: clear the previous overlay immediately — otherwise `chunkLabel`
 * updates (Chunk 1 → 19) while the old box stays put during the Lit wait.
 */
export function useChunkHighlightOverlay({
  ready,
  hostRef,
  viewerRef,
  scrollContainerRef,
  chunkLabel,
  highlightKey,
  fallbackPage,
  applyStyles,
}: {
  ready: boolean;
  hostRef: RefObject<HTMLDivElement | null>;
  viewerRef: RefObject<DoclingImgElement | null>;
  scrollContainerRef?: RefObject<HTMLElement | null>;
  chunkLabel?: string;
  highlightKey: string;
  fallbackPage?: number | null;
  applyStyles: () => void;
}) {
  const [overlay, setOverlay] = useState<OverlayBox | null>(null);

  useLayoutEffect(() => {
    if (!ready || !chunkLabel) {
      setOverlay(null);
      return;
    }
    // Selection fingerprint (label + item refs + page) — read so the effect
    // re-runs when only refs/page change under the same chunk label.
    void highlightKey;

    const host = hostRef.current;
    const viewer = viewerRef.current;
    // Drop stale "Chunk N" chrome before the new geometry is ready.
    setOverlay(null);
    if (!host || !viewer) return;

    const beforeSignature = hitRectsSignature(collectChunkHitRects(viewer));
    applyStyles();

    let cancelled = false;
    let timeoutId: number | undefined;

    const resolvePageNo = (): number | null => {
      if (typeof fallbackPage !== "number") return null;
      for (const pageNo of [fallbackPage, fallbackPage + 1, fallbackPage - 1]) {
        if (pageNo < 1) continue;
        if (findDoclingPageElement(viewer, pageNo)) return pageNo;
      }
      return fallbackPage;
    };

    const preferredScrollContainers = () => [
      scrollContainerRef?.current,
      findScrollParent(host),
    ];

    const scrollToAnchor = (anchor: Element | null) => {
      if (!anchor) return;
      scrollElementThroughAncestors(anchor, preferredScrollContainers());
    };

    const placeOverlay = (hitEls: Element[]) => {
      if (cancelled || hitEls.length === 0) {
        if (!cancelled) setOverlay(null);
        return;
      }
      const hitRects = hitEls.map((el) => el.getBoundingClientRect());
      const hostRect = host.getBoundingClientRect();
      setOverlay(
        unionRect(hitRects, hostRect, host.scrollTop, host.scrollLeft),
      );
    };

    const pageNo = resolvePageNo();
    const pageAnchor =
      pageNo != null ? findDoclingPageAnchor(viewer, pageNo) : null;

    const finish = (hitEls: Element[], refineScroll: boolean) => {
      if (cancelled) return;
      // Overlay is host-relative so it stays correct during the smooth scroll.
      placeOverlay(hitEls);
      // Single smooth scroll only — a second scrollTo cancels the animation.
      const anchor =
        refineScroll && hitEls[0] ? hitEls[0] : (pageAnchor ?? hitEls[0]);
      scrollToAnchor(anchor ?? null);
    };

    const pageItemElements = (): SVGRectElement[] => {
      if (pageNo == null) return [];
      return collectPageItemElements(viewer, pageNo);
    };

    const placeFromGeometry = () => {
      if (cancelled) return;

      const hitEls = collectChunkHitElements(viewer);
      const signature = hitRectsSignature(
        hitEls.map((el) => el.getBoundingClientRect()),
      );
      const hitsAreFresh =
        hitEls.length > 0 &&
        (beforeSignature === "" || signature !== beforeSignature);

      if (hitsAreFresh) {
        finish(hitEls, true);
        return;
      }

      // Fall back to page geometry so the Chunk N frame still appears.
      const pageEls = pageItemElements();
      if (pageEls.length > 0) {
        finish(pageEls, false);
        return;
      }
      if (pageAnchor) {
        finish([pageAnchor], false);
      }
    };

    const timeout = new Promise<void>((resolve) => {
      timeoutId = window.setTimeout(resolve, LIT_UPDATE_TIMEOUT_MS);
    });

    void Promise.race([waitForDoclingLitPaint(viewer), timeout]).then(() => {
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
        timeoutId = undefined;
      }
      placeFromGeometry();
    });

    return () => {
      cancelled = true;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [
    ready,
    chunkLabel,
    highlightKey,
    fallbackPage,
    applyStyles,
    hostRef,
    viewerRef,
    scrollContainerRef,
  ]);

  return overlay;
}
