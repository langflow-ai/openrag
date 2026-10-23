import type {
  ChunkResult,
  File,
  RelevanceTier,
} from "@/app/api/queries/useGetSearchQuery";
import { cn } from "@/lib/utils";

export interface RelevanceBreakdown {
  tier: RelevanceTier;
  tierLabel: string;
  title: string;
  reasoning: string;
  keywordTier: RelevanceTier;
  keywordDetail: string;
  keywordMentionCount: number;
  meaningTier: RelevanceTier;
  meaningDetail: string;
  matchedChunksCount: number;
  topChunkScorePct: number | null;
}

export const RELEVANCE_PILL_STYLES: Record<RelevanceTier, string> = {
  high: "border-emerald-500/80 text-emerald-700 bg-emerald-50/50 dark:border-emerald-500/70 dark:text-emerald-300 dark:bg-emerald-950/30",
  medium:
    "border-amber-500/80 text-amber-700 bg-amber-50/50 dark:border-amber-500/70 dark:text-amber-300 dark:bg-amber-950/30",
  low: "border-slate-400/80 text-slate-600 bg-slate-50/50 dark:border-slate-500/70 dark:text-slate-400 dark:bg-slate-900/30",
};

export const RELEVANCE_TEXT_COLORS: Record<RelevanceTier, string> = {
  high: "text-emerald-600 dark:text-emerald-400 font-semibold",
  medium: "text-amber-600 dark:text-amber-400 font-semibold",
  low: "text-slate-600 dark:text-slate-400 font-semibold",
};

export function getScoreTier(pct: number): RelevanceTier {
  return pct >= 65 ? "high" : pct >= 35 ? "medium" : "low";
}

/**
 * Deterministic (non-LLM) explanation of search ranking factors based on
 * vector embeddings and OpenSearch BM25 keyword highlights.
 */
export function getRelevanceReasoning(data?: File): RelevanceBreakdown {
  const tier: RelevanceTier = data?.relevanceTier ?? "low";
  const tierLabel =
    tier === "high" ? "High" : tier === "medium" ? "Medium" : "Low";
  const title = `Why it's ranked ${tierLabel}`;

  const chunks = data?.chunks ?? [];
  const matchedChunksCount = data?.chunkCount ?? chunks.length;
  const topChunkScorePct =
    typeof data?.maxScore === "number" ? Math.round(data.maxScore * 100) : null;

  // Count total <mark> tags across all chunk highlights
  const keywordMentionCount = chunks.reduce((total, c) => {
    const highlights = c.highlights ?? [];
    return (
      total +
      highlights.reduce((sub, h) => sub + (h.match(/<mark>/g)?.length ?? 0), 0)
    );
  }, 0);

  // Keyword signal tier
  const keywordTier: RelevanceTier =
    keywordMentionCount >= 3
      ? "high"
      : keywordMentionCount >= 1
        ? "medium"
        : "low";

  // Meaning / vector signal tier
  const isSemanticMatch = Boolean(data?.isSemanticMatch);
  const score = data?.maxScore ?? 0;
  const meaningTier: RelevanceTier =
    score >= 0.65 ? "high" : score >= 0.35 ? "medium" : "low";

  const meaningDetail =
    meaningTier === "high"
      ? "Strong"
      : meaningTier === "medium"
        ? "Moderate"
        : "Weak";

  // Plain-English, user-friendly reasoning explanation
  let reasoning = "";
  if (tier === "high") {
    if (isSemanticMatch || keywordMentionCount === 0) {
      reasoning =
        "Matched by meaning rather than exact words — the content directly discusses this topic.";
    } else if (matchedChunksCount === 1 && keywordMentionCount >= 2) {
      reasoning =
        "Mostly one repeated passage, which boosts the keyword score.";
    } else if (keywordMentionCount >= 3 && matchedChunksCount > 1) {
      reasoning =
        "Your search terms appear frequently across multiple sections of this document.";
    } else {
      reasoning =
        "Strong overall match — discusses this topic directly and includes your search terms.";
    }
  } else if (tier === "medium") {
    if (isSemanticMatch || keywordMentionCount === 0) {
      reasoning =
        "Related topic — discusses concepts relevant to your search, but uses different wording.";
    } else if (matchedChunksCount === 1) {
      reasoning =
        "Mentions your keywords in one section with moderate overall relevance.";
    } else if (keywordMentionCount > 0) {
      reasoning =
        "Partial match — mentions some search terms and shares related topic context.";
    } else {
      reasoning =
        "Moderate overlap with your search terms across parts of the document.";
    }
  } else {
    if (keywordMentionCount === 0) {
      reasoning =
        "Weak connection — only minor conceptual overlap with your search topic.";
    } else {
      reasoning =
        "Few isolated keyword matches, but the document is mostly about other topics.";
    }
  }

  const keywordDetail =
    keywordMentionCount > 0
      ? `Mentioned ${keywordMentionCount} time${keywordMentionCount !== 1 ? "s" : ""}`
      : "0 direct matches (concept match)";

  return {
    tier,
    tierLabel,
    title,
    reasoning,
    keywordTier,
    keywordDetail,
    keywordMentionCount,
    meaningTier,
    meaningDetail,
    matchedChunksCount,
    topChunkScorePct,
  };
}

export interface ChunkRelevanceBreakdown {
  tier: RelevanceTier;
  tierLabel: string;
  title: string;
  reasoning: string;
  keywordTier: RelevanceTier;
  keywordDetail: string;
  keywordMentionCount: number;
  meaningTier: RelevanceTier;
  meaningDetail: string;
  chunkScorePct: number | null;
}

/**
 * Deterministic breakdown explaining a single chunk's relevance ranking factors
 * (semantic meaning score vs. exact keyword matches).
 */
export function getChunkRelevanceReasoning(
  chunk: ChunkResult,
  scoreTier?: RelevanceTier,
  scoreLabel?: string,
  isSemanticMatch?: boolean,
): ChunkRelevanceBreakdown {
  const highlights = chunk.highlights ?? [];
  const keywordMentionCount = highlights.reduce(
    (total, h) => total + (h.match(/<mark>/g)?.length ?? 0),
    0,
  );

  const keywordTier: RelevanceTier =
    keywordMentionCount >= 3
      ? "high"
      : keywordMentionCount >= 1
        ? "medium"
        : "low";

  let chunkScorePct: number | null = null;
  if (scoreLabel && scoreLabel.endsWith("%")) {
    const parsed = Number.parseInt(scoreLabel, 10);
    if (!Number.isNaN(parsed)) {
      chunkScorePct = parsed;
    }
  }
  if (chunkScorePct === null) {
    if (typeof chunk.normalizedScore === "number") {
      chunkScorePct = Math.round(chunk.normalizedScore * 100);
    } else if (typeof chunk.score === "number" && chunk.score > 0) {
      chunkScorePct = Math.round(chunk.score * 100);
    }
  }

  const tier: RelevanceTier =
    scoreTier ?? (chunkScorePct !== null ? getScoreTier(chunkScorePct) : "low");
  const tierLabel =
    tier === "high" ? "High" : tier === "medium" ? "Medium" : "Low";
  const title = `Why it's ranked ${tierLabel}`;

  const meaningTier: RelevanceTier =
    chunkScorePct !== null
      ? chunkScorePct >= 65
        ? "high"
        : chunkScorePct >= 35
          ? "medium"
          : "low"
      : tier;

  const meaningDetail =
    meaningTier === "high"
      ? "Strong"
      : meaningTier === "medium"
        ? "Moderate"
        : "Weak";

  let reasoning = "";
  if (tier === "high") {
    if (isSemanticMatch || keywordMentionCount === 0) {
      reasoning =
        "Matched by meaning rather than exact words — this passage directly discusses the concept.";
    } else if (keywordMentionCount >= 3) {
      reasoning =
        "Your search terms appear prominently in this section with strong conceptual relevance.";
    } else {
      reasoning =
        "Strong overall match — discusses this topic directly and includes your search terms.";
    }
  } else if (tier === "medium") {
    if (isSemanticMatch || keywordMentionCount === 0) {
      reasoning =
        "Related topic — discusses concepts relevant to your search, but uses different wording.";
    } else if (keywordMentionCount > 0) {
      reasoning =
        "Contains your search terms with moderate semantic overlap in this section.";
    } else {
      reasoning = "Moderate overlap with your search query in this section.";
    }
  } else {
    if (keywordMentionCount === 0) {
      reasoning =
        "Weak connection — minor conceptual overlap with your search topic.";
    } else {
      reasoning =
        "Contains minor keyword mentions, but low overall relevance to your search query.";
    }
  }

  const keywordDetail =
    keywordMentionCount > 0
      ? `Mentioned ${keywordMentionCount} time${keywordMentionCount !== 1 ? "s" : ""}`
      : "0 direct matches (concept match)";

  return {
    tier,
    tierLabel,
    title,
    reasoning,
    keywordTier,
    keywordDetail,
    keywordMentionCount,
    meaningTier,
    meaningDetail,
    chunkScorePct,
  };
}

/**
 * 3-bar signal indicator matching `.ıl` style.
 * High: 3 bars active
 * Medium: 2 bars active
 * Low: 1 bar active
 */
export function WifiSignalIcon({
  tier = "low",
  className,
  size = 13,
}: {
  tier?: RelevanceTier | "high" | "medium" | "low" | null;
  className?: string;
  size?: number;
}) {
  const activeCount = tier === "high" ? 3 : tier === "medium" ? 2 : 1;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      fill="currentColor"
      className={cn("shrink-0", className)}
      aria-hidden="true"
    >
      {/* Bar 1 (Short / Dot height) */}
      <rect
        x="1.5"
        y="9.5"
        width="2.5"
        height="3"
        rx="0.8"
        className={
          activeCount >= 1 ? "opacity-100" : "opacity-25 dark:opacity-20"
        }
      />
      {/* Bar 2 (Medium height) */}
      <rect
        x="5.5"
        y="6"
        width="2.5"
        height="6.5"
        rx="0.8"
        className={
          activeCount >= 2 ? "opacity-100" : "opacity-25 dark:opacity-20"
        }
      />
      {/* Bar 3 (Tall height) */}
      <rect
        x="9.5"
        y="2.5"
        width="2.5"
        height="10"
        rx="0.8"
        className={
          activeCount >= 3 ? "opacity-100" : "opacity-25 dark:opacity-20"
        }
      />
    </svg>
  );
}
