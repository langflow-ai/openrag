"use client";

import { ExternalLink, Eye, X } from "lucide-react";
import { useRef, useState } from "react";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import type { ToolCallResult } from "@/app/chat/_types/types";
import { PopoverContent } from "@/components/ui/popover";
import { DEFAULT_KNOWLEDGE_SETTINGS } from "@/lib/constants";
import {
  getDownloadSourceUrl,
  getPreviewSourceUrl,
  getSourcePreviewKind,
} from "@/lib/source-url";
import { cn } from "@/lib/utils";

interface ChunkPopupProps {
  onClose: () => void;
  chunkNumber: number;
  filename: string;
  score: number | string;
  sourceText: string;
  item: ToolCallResult;
  showViewDocument?: boolean;
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
  return resolvedScore === undefined ? "--" : `${resolvedScore.toFixed(2)}`;
};

const formatPage = (item: ToolCallResult): string | null => {
  const page = toNumber(getMetadataValue(item, "page"));
  if (page === undefined || page <= 0) return null;
  return `Page ${page}`;
};

export function ChunkPopup({
  onClose,
  chunkNumber,
  filename,
  score,
  sourceText,
  item,
  showViewDocument = true,
}: ChunkPopupProps) {
  const { data: settings } = useGetSettingsQuery();
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const [showPreview, setShowPreview] = useState(false);

  const sourceUrl = getDownloadSourceUrl(item.source_url ?? undefined);
  const previewKind = getSourcePreviewKind(filename);
  const previewUrl = getPreviewSourceUrl(sourceUrl);
  const canPreview = Boolean(
    showViewDocument && previewKind && previewUrl && sourceUrl,
  );
  const hasUrl = showViewDocument && Boolean(sourceUrl);
  const parser = formatParser(item, filename);
  const scoreLabel = formatScore(item, score);
  const pageLabel = formatPage(item);
  const page = toNumber(getMetadataValue(item, "page"));
  const displayedPreviewUrl =
    previewUrl && filename.toLowerCase().endsWith(".pdf") && page && page > 0
      ? `${previewUrl.split("#", 1)[0]}#page=${Math.floor(page)}`
      : previewUrl;
  const splitConfig = formatSplitConfig(
    item,
    settings?.knowledge?.chunk_size ?? DEFAULT_KNOWLEDGE_SETTINGS.chunk_size,
    settings?.knowledge?.chunk_overlap ??
      DEFAULT_KNOWLEDGE_SETTINGS.chunk_overlap,
  );
  const embedding = formatEmbeddingModel(item);

  return (
    <PopoverContent
      side="top"
      align="center"
      sideOffset={10}
      collisionPadding={12}
      onOpenAutoFocus={(event) => {
        event.preventDefault();
        closeButtonRef.current?.focus();
      }}
      className={cn(
        "z-50 bg-background-dark border border-border rounded-xl shadow-2xl flex flex-col overflow-hidden text-foreground backdrop-blur-xl p-0",
        showPreview
          ? "w-[min(calc(100vw-24px),52rem)] max-h-[min(88vh,48rem)]"
          : "w-[min(calc(100vw-24px),32rem)] max-h-[min(72vh,34rem)]",
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between p-4 pb-3">
        <div className="flex items-center gap-2.5 min-w-0 pr-4">
          <span className="shrink-0 bg-muted/80 text-accent-purple-foreground font-semibold px-2.5 py-0.5 rounded-full text-xs">
            Chunk {chunkNumber}
          </span>
          <h3
            className="text-sm font-bold text-foreground truncate"
            title={filename}
          >
            {filename}
          </h3>
          {pageLabel && (
            <span className="shrink-0 text-muted-foreground text-xxs font-semibold">
              {pageLabel}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="bg-accent-purple/20 border border-accent-purple text-accent-purple-foreground font-mono px-2 py-0.5 rounded text-xs select-none">
            {scoreLabel}
          </span>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground transition-colors p-1 hover:bg-muted rounded-md"
            aria-label="Close dialog"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Metadata Sub-header */}
      <div className="grid grid-cols-3 border-y border-border text-xs text-muted-foreground py-2.5 px-4  select-none">
        <div
          className="border-r border-border text-center truncate pr-1"
          title={parser}
        >
          {parser}
        </div>
        <div
          className="border-r border-border text-center truncate px-1"
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
          {showPreview && displayedPreviewUrl && previewKind && (
            <div className="space-y-2 pb-3">
              <span className="text-muted-foreground text-[10px] font-extrabold uppercase tracking-wider block">
                Original document
              </span>
              <div className="flex h-72 items-center justify-center overflow-hidden rounded-lg border border-border bg-white">
                {previewKind === "image" ? (
                  // biome-ignore lint/performance/noImgElement: authenticated source URLs are not supported by next/image.
                  <img
                    src={displayedPreviewUrl}
                    alt={`Preview of ${filename}`}
                    className="max-h-full max-w-full object-contain"
                  />
                ) : (
                  <iframe
                    src={displayedPreviewUrl}
                    title={`Preview of ${filename}`}
                    className="h-full w-full bg-white"
                  />
                )}
              </div>
            </div>
          )}
          <div className="flex justify-between items-center">
            <span className="text-muted-foreground text-[10px] font-extrabold uppercase tracking-wider block">
              Source text
            </span>
            <div className="flex items-center gap-3">
              {hasUrl && (
                <button
                  type="button"
                  onClick={() => {
                    if (canPreview) {
                      setShowPreview((visible) => !visible);
                      return;
                    }
                    window.open(sourceUrl, "_blank", "noopener,noreferrer");
                  }}
                  className="text-accent-purple-foreground hover:text-primary-hover text-[10px] font-bold flex items-center gap-1 hover:underline transition-all cursor-pointer"
                >
                  {canPreview ? (
                    <Eye className="w-3 h-3" />
                  ) : (
                    <ExternalLink className="w-3 h-3" />
                  )}
                  {canPreview
                    ? showPreview
                      ? "Hide preview"
                      : "Preview document"
                    : "View document"}
                </button>
              )}
            </div>
          </div>
          <div className="bg-background/40 text-xs text-foreground p-4 rounded-lg border border-border leading-relaxed font-normal whitespace-pre-wrap select-text max-h-72 overflow-y-auto">
            {sourceText}
          </div>
        </div>
      </div>
    </PopoverContent>
  );
}
