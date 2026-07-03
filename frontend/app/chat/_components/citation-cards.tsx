"use client";

import { ExternalLink, FileText } from "lucide-react";
import type { CitedSource } from "@/components/markdown-citations";
import { deriveDisplayFilename } from "@/components/markdown-renderer";

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
  onCardRef?: (index: number, element: HTMLButtonElement | null) => void;
}

export function CitationCards({
  citedSources,
  activeCardIndex,
  onCardClick,
  onCardRef,
}: CitationCardsProps) {
  if (!citedSources || citedSources.length === 0) return null;

  return (
    <div
      className="mt-4 flex flex-wrap gap-2.5 w-full select-none"
      data-testid="citation-cards"
    >
      {citedSources.map(({ item, index }) => {
        const filename = deriveDisplayFilename(
          item.data?.file_path,
          item.filename,
          "document",
        );
        const score = toNumber(item.score);

        const page = item.page ?? item.data?.page;

        const hasUrl = !!item.source_url;
        const isActive = index === activeCardIndex;

        const handleClick = (event: React.MouseEvent<HTMLButtonElement>) => {
          onCardClick?.(index, event.currentTarget);
        };

        return (
          <button
            type="button"
            key={
              item.chunk_id ||
              item.id ||
              item.data?.file_path ||
              item.filename ||
              index
            }
            ref={(element) => onCardRef?.(index, element)}
            onClick={handleClick}
            className={`group relative flex items-center px-3 py-2 rounded-lg border transition-all duration-200 shadow-sm cursor-pointer text-left ${
              isActive
                ? "bg-muted border-primary-hover/50"
                : "bg-muted/50 hover:bg-muted border-muted hover:border-primary-hover/50"
            }`}
            title={
              hasUrl
                ? `View source chunk details (has link: ${item.source_url})`
                : "View source chunk details"
            }
          >
            {/* Index Badge */}
            <div className="flex items-center justify-center shrink-0 text-mmd text-accent-purple-foreground mr-2.5">
              {index}
            </div>

            {/* File Icon */}
            <div className="bg-muted p-0.5 rounded flex mr-3 shrink-0">
              <FileText className="w-3 h-3 text-muted-foreground shrink-0" />
            </div>

            {/* Document details */}
            <div className="flex flex-col min-w-0 pr-1">
              <span className="text-mmd text-primary-hover truncate max-w-[160px] leading-tight">
                {filename}
              </span>
              <span className="text-xxs text-muted-foreground mt-1 leading-none">
                {page !== null && page !== undefined ? `page ${page}` : ""}
                {page !== null && page !== undefined && score !== undefined && score > 0 && ` • `}
                {score !== undefined &&
                  score > 0 &&
                  `score ${score.toFixed(2)}`}
              </span>
            </div>

            {/* External link indicator */}
            {hasUrl && (
              <ExternalLink className="w-2.5 h-2.5 text-accent-purple-foreground opacity-0 group-hover:opacity-100 transition-opacity ml-1.5 shrink-0" />
            )}
          </button>
        );
      })}
    </div>
  );
}
