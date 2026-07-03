"use client";

import { ExternalLink, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import type { ToolCallResult } from "@/app/chat/_types/types";
import { DEFAULT_KNOWLEDGE_SETTINGS } from "@/lib/constants";

type AnchorRect = Pick<
  DOMRect,
  "bottom" | "height" | "left" | "right" | "top" | "width"
>;

type PopoverPosition = {
  arrowLeft: number;
  left: number;
  placement: "above" | "below";
  top: number;
};

interface ChunkPopupProps {
  isOpen: boolean;
  onClose: () => void;
  anchorElement: HTMLElement | null;
  chunkNumber: number;
  filename: string;
  score: number | string;
  sourceText: string;
  item: ToolCallResult;
}

const getMetadataValue = (
  item: ToolCallResult,
  key:
    | "embedding_model"
    | "parser"
    | "chunk_size"
    | "chunk_overlap"
    | "page"
    | "score",
): unknown =>
  item[key] ??
  item.data?.[key] ??
  item.metadata?.[key] ??
  item.data?.metadata?.[key];

const toNumber = (value: unknown): number | undefined => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
};

const formatParser = (item: ToolCallResult, filename: string): string => {
  const parser = getMetadataValue(item, "parser");
  if (typeof parser === "string" && parser.trim()) {
    return parser.trim();
  }
  const fileExt = filename.split(".").pop()?.toLowerCase() || "";
  if (fileExt === "txt" || fileExt === "md") return "Text Parser";
  return "Docling Serve 1.20.0";
};

const formatSplitConfig = (
  item: ToolCallResult,
  fallbackChunkSize?: number,
  fallbackChunkOverlap?: number,
): string => {
  const chunkSize =
    toNumber(getMetadataValue(item, "chunk_size")) ?? fallbackChunkSize;
  const chunkOverlap =
    toNumber(getMetadataValue(item, "chunk_overlap")) ?? fallbackChunkOverlap;
  if (chunkSize !== undefined && chunkOverlap !== undefined) {
    return `${chunkSize} tok - ${chunkOverlap} overlap`;
  }
  if (chunkSize !== undefined) {
    return `${chunkSize} tok`;
  }
  return "Split config unavailable";
};

const formatEmbeddingModel = (item: ToolCallResult): string => {
  const embeddingModel = getMetadataValue(item, "embedding_model");
  if (typeof embeddingModel === "string" && embeddingModel.trim()) {
    return embeddingModel.trim();
  }
  return "Embedding model unavailable";
};

const formatScore = (
  item: ToolCallResult,
  fallbackScore: number | string,
): string => {
  const score = toNumber(getMetadataValue(item, "score"));
  const numericFallback = toNumber(fallbackScore);
  const resolvedScore =
    score ??
    (numericFallback !== undefined && numericFallback > 0
      ? numericFallback
      : undefined);
  return resolvedScore === undefined
    ? "Score --"
    : `Score ${resolvedScore.toFixed(2)}`;
};

const formatPage = (item: ToolCallResult): string | null => {
  const page = toNumber(getMetadataValue(item, "page"));
  if (page === undefined || page <= 0) return null;
  return `Page ${page}`;
};

export function ChunkPopup({
  isOpen,
  onClose,
  anchorElement,
  chunkNumber,
  filename,
  score,
  sourceText,
  item,
}: ChunkPopupProps) {
  const { data: settings } = useGetSettingsQuery();
  const popoverRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<PopoverPosition | null>(null);

  const updatePosition = useCallback(() => {
    if (!isOpen || !anchorElement || !popoverRef.current) {
      setPosition(null);
      return;
    }

    const margin = 12;
    const gap = 10;
    const anchorRect: AnchorRect = anchorElement.getBoundingClientRect();
    const popoverRect = popoverRef.current.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const maxLeft = Math.max(
      margin,
      viewportWidth - popoverRect.width - margin,
    );
    const anchorCenter = anchorRect.left + anchorRect.width / 2;
    const left = Math.min(
      Math.max(anchorCenter - popoverRect.width / 2, margin),
      maxLeft,
    );
    const topAbove = anchorRect.top - popoverRect.height - gap;
    const fitsAbove = topAbove >= margin;
    const maxTop = Math.max(
      margin,
      viewportHeight - popoverRect.height - margin,
    );
    const top = fitsAbove
      ? topAbove
      : Math.min(Math.max(anchorRect.bottom + gap, margin), maxTop);
    const arrowLeft = Math.min(
      Math.max(anchorCenter - left, 18),
      popoverRect.width - 18,
    );

    setPosition({
      arrowLeft,
      left,
      placement: fitsAbove ? "above" : "below",
      top,
    });
  }, [anchorElement, isOpen]);

  useLayoutEffect(() => {
    updatePosition();
  }, [updatePosition]);

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };

    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, onClose, updatePosition]);

  if (!isOpen) return null;

  const hasUrl = !!item.source_url;
  const parser = formatParser(item, filename);
  const scoreLabel = formatScore(item, score);
  const pageLabel = formatPage(item);
  const splitConfig = formatSplitConfig(
    item,
    settings?.knowledge?.chunk_size ?? DEFAULT_KNOWLEDGE_SETTINGS.chunk_size,
    settings?.knowledge?.chunk_overlap ??
      DEFAULT_KNOWLEDGE_SETTINGS.chunk_overlap,
  );
  const embedding = formatEmbeddingModel(item);

  return (
    <AnimatePresence>
      <>
        <motion.button
          type="button"
          aria-label="Close chunk details"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          className="fixed inset-0 z-40 cursor-default bg-transparent"
        />

        <motion.div
          ref={popoverRef}
          initial={{ opacity: 0, scale: 0.98, y: 6 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.98, y: 6 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
          style={{
            left: position?.left ?? 12,
            top: position?.top ?? 12,
            width: "min(calc(100vw - 24px), 32rem)",
          }}
          className="fixed z-50 bg-zinc-950/95 border border-zinc-800/80 rounded-xl shadow-2xl flex flex-col max-h-[min(72vh,34rem)] overflow-hidden text-zinc-100 backdrop-blur-xl"
        >
          {position && (
            <div
              className={`absolute h-3 w-3 rotate-45 bg-zinc-950 border-zinc-800/80 ${
                position.placement === "above"
                  ? "-bottom-1.5 border-b border-r"
                  : "-top-1.5 border-l border-t"
              }`}
              style={{ left: position.arrowLeft - 6 }}
            />
          )}

          {/* Header */}
          <div className="flex items-center justify-between p-4 pb-3">
            <div className="flex items-center gap-2.5 min-w-0 pr-4">
              <span className="shrink-0 bg-violet-900/35 border border-violet-850/65 text-violet-400 font-bold px-2.5 py-0.5 rounded-full text-xs">
                Chunk {chunkNumber}
              </span>
              <h3
                className="text-sm font-bold text-zinc-100 truncate"
                title={filename}
              >
                {filename}
              </h3>
              {pageLabel && (
                <span className="shrink-0 text-zinc-500 text-[10px] font-bold">
                  {pageLabel}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <span className="bg-violet-950/60 border border-violet-900/40 text-violet-400 font-semibold px-2 py-0.5 rounded text-xs select-none">
                {scoreLabel}
              </span>
              <button
                onClick={onClose}
                className="text-zinc-400 hover:text-zinc-200 transition-colors p-1 hover:bg-zinc-900/80 rounded-md"
                aria-label="Close dialog"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Metadata Sub-header */}
          <div className="grid grid-cols-3 border-y border-zinc-900 bg-zinc-950/40 text-[10px] text-zinc-400 py-2.5 px-4 font-semibold select-none">
            <div
              className="border-r border-zinc-900 text-center truncate pr-1"
              title={parser}
            >
              {parser}
            </div>
            <div
              className="border-r border-zinc-900 text-center truncate px-1"
              title={splitConfig}
            >
              {splitConfig}
            </div>
            <div className="text-center truncate pl-1" title={embedding}>
              {embedding}
            </div>
          </div>

          {/* Body Content */}
          <div className="p-4 flex-1 overflow-y-auto min-h-0">
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-zinc-500 text-[10px] font-extrabold uppercase tracking-wider block">
                  Source text
                </span>
                <div className="flex items-center gap-3">
                  {hasUrl && (
                    <button
                      onClick={() =>
                        window.open(
                          item.source_url!,
                          "_blank",
                          "noopener,noreferrer",
                        )
                      }
                      className="text-violet-400 hover:text-violet-300 text-[10px] font-bold flex items-center gap-1 hover:underline transition-all cursor-pointer"
                    >
                      <ExternalLink className="w-3 h-3" />
                      View document
                    </button>
                  )}
                </div>
              </div>
              <div className="bg-zinc-900/40 text-xs text-zinc-300 p-4 rounded-lg border border-zinc-800/40 leading-relaxed font-normal whitespace-pre-wrap select-text max-h-72 overflow-y-auto">
                {sourceText}
              </div>
            </div>
          </div>

          {/* Footer (No feedback buttons) */}
          <div className="p-3 bg-zinc-950 border-t border-zinc-900 flex justify-end">
            <button
              onClick={onClose}
              className="px-4 py-1.5 bg-zinc-900 border border-zinc-800 hover:bg-zinc-800 rounded-lg text-xs font-semibold text-zinc-300 transition-colors cursor-pointer"
            >
              Close
            </button>
          </div>
        </motion.div>
      </>
    </AnimatePresence>
  );
}
