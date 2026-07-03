"use client";

import { ExternalLink, FileText } from "lucide-react";
import type { CitedSource } from "@/components/markdown-renderer";
import { getChunkNumber } from "@/components/markdown-renderer";

const toNumber = (value: unknown): number | undefined => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
};

interface CitationCardsProps {
  citedSources: CitedSource[];
  activeCardIndex?: number | null;
  onCardClick?: (index: number, anchorElement: HTMLElement) => void;
}

export function CitationCards({
  citedSources,
  activeCardIndex,
  onCardClick,
}: CitationCardsProps) {
  if (!citedSources || citedSources.length === 0) return null;

  return (
    <div
      className="mt-4 flex flex-wrap gap-2.5 w-full select-none"
      data-testid="citation-cards"
    >
      {citedSources.map(({ item, index }) => {
        const filePath = item.data?.file_path || item.filename || "document";
        // Extract just the filename from path
        const filename = filePath.split("/").pop() || filePath;
        const score = toNumber(item.score);

        // Extract chunk index safely
        const chunkId = item.chunk_id || item.id;
        const chunkNum = getChunkNumber(chunkId);

        const hasUrl = !!item.source_url;
        const isActive = index === activeCardIndex;

        const handleClick = (event: React.MouseEvent<HTMLButtonElement>) => {
          onCardClick?.(index, event.currentTarget);
        };

        return (
          <button
            type="button"
            key={index}
            onClick={handleClick}
            className={`group relative flex items-center p-2.5 rounded-lg border transition-all duration-200 shadow-sm cursor-pointer text-left ${
              isActive
                ? "bg-violet-950/30 border-violet-550 ring-2 ring-violet-500/35 scale-[1.01] shadow-md shadow-violet-950/25"
                : "bg-violet-950/12 hover:bg-violet-950/24 border-violet-900/30 hover:border-violet-850/55"
            }`}
            title={
              hasUrl
                ? `View source chunk details (has link: ${item.source_url})`
                : "View source chunk details"
            }
          >
            {/* Index Badge */}
            <div className="flex items-center justify-center shrink-0 w-5 h-5 rounded bg-violet-950/40 border border-violet-900/50 text-[10px] font-bold text-violet-400 mr-2.5">
              {index}
            </div>

            {/* File Icon */}
            <FileText className="w-4 h-4 text-violet-400/90 mr-2 shrink-0" />

            {/* Document details */}
            <div className="flex flex-col min-w-0 pr-1">
              <span className="text-xs font-semibold text-zinc-100 truncate max-w-[160px] leading-tight">
                {filename}
              </span>
              <span className="text-[10px] text-zinc-400 font-medium mt-0.5 leading-none">
                {chunkNum !== null ? `chunk ${chunkNum}` : "chunk 1"}
                {score !== undefined &&
                  score > 0 &&
                  ` • score ${score.toFixed(2)}`}
              </span>
            </div>

            {/* External link indicator */}
            {hasUrl && (
              <ExternalLink className="w-2.5 h-2.5 text-violet-400 opacity-0 group-hover:opacity-100 transition-opacity ml-1.5 shrink-0" />
            )}
          </button>
        );
      })}
    </div>
  );
}
