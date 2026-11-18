type SemanticTier = "high" | "medium" | "low";

// emerald / amber / slate — mirrors green (strong), yellow (medium), and grey (weak).
const SEMANTIC_MARK_CLASS: Record<SemanticTier, string> = {
  high: "bg-emerald-100 dark:bg-emerald-950/70 text-emerald-900 dark:text-emerald-100 border-b-[3px] border-emerald-500 dark:border-emerald-400 rounded-[2px] px-[2px] font-medium not-italic",
  medium:
    "bg-amber-100 dark:bg-amber-950/60 text-amber-900 dark:text-amber-100 border-b-2 border-amber-500 dark:border-amber-400 rounded-[2px] px-[2px] not-italic",
  low: "bg-slate-100 dark:bg-slate-900/60 text-slate-800 dark:text-slate-200 border-b border-slate-400 dark:border-slate-500 rounded-[2px] px-[2px] not-italic",
};

interface HighlightedTextProps {
  /** Highlight fragments from OpenSearch (may contain <mark> tags). */
  highlights: string[];
  /** Plain text shown when highlights is empty. */
  fallbackText: string;
  className?: string;
  /** When true, semantic highlighting is applied. */
  isSemanticMatch?: boolean;
  /** Active search query for semantic phrase/sentence highlighting when no literal marks exist. */
  searchQuery?: string;
  /** Relevance tier — drives the colour of the semantic highlight mark. Defaults to "high". */
  scoreTier?: SemanticTier;
  /** Replaces the default yellow-background style of matched terms. */
  markClassName?: string;
}

const DEFAULT_MARK_CLASS =
  "bg-yellow-200 dark:bg-yellow-800 text-foreground rounded-[2px] px-px not-italic";

/**
 * Bold + underline match style for one-line previews (search suggestions and
 * the table). `bg-transparent` is required: a bare <mark> gets the browser's
 * yellow background, which is unreadable against theme foreground colours.
 * Colours come from theme tokens so it follows light and dark mode.
 */
export const BOLD_MATCH_CLASS =
  "bg-transparent text-foreground font-semibold underline decoration-1 underline-offset-2 not-italic";

/** Surrounding (non-matched) preview text: readable, but below the match. */
export const PREVIEW_TEXT_CLASS = "text-foreground/70";

/**
 * Parse a single fragment string like "foo <mark>bar</mark> baz" into an
 * array of React nodes, converting `<mark>` elements to styled spans.
 */
function parseFragment(
  fragment: string,
  keyPrefix: string,
  markClassName: string,
  semanticTier?: SemanticTier,
): React.ReactNode {
  const parts = fragment.split(/(<mark>.*?<\/mark>)/g);
  let partId = 0;
  return parts.map((part) => {
    const key = `${keyPrefix}-p${partId++}`;
    if (part.startsWith("<mark>") && part.endsWith("</mark>")) {
      const inner = part.slice(6, -7); // strip <mark> and </mark>
      return (
        <mark
          key={key}
          className={
            semanticTier ? SEMANTIC_MARK_CLASS[semanticTier] : markClassName
          }
        >
          {inner}
        </mark>
      );
    }
    return part ? <span key={key}>{part}</span> : null;
  });
}

const CJK_REGEX =
  /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]/;

function isFormattingNoise(s: string): boolean {
  const trimmed = s.trim();
  if (!trimmed || trimmed.length < 4) return true;
  if (new RegExp("^\\|?[\\s|:\\-]+\\|?$").test(trimmed)) return true;
  if (/^[-*=_]{3,}$/.test(trimmed)) return true;
  if (/^`{3,}/.test(trimmed)) return true;
  if (/^#{1,6}\s*$/.test(trimmed)) return true;
  if (!/[a-zA-Z]{3,}/.test(trimmed) && !CJK_REGEX.test(trimmed)) return true;
  return false;
}

function highlightSemanticSpan(
  text: string,
  query?: string,
  tier: SemanticTier = "high",
): React.ReactNode {
  if (!text || !query?.trim()) return text;

  const markClass = SEMANTIC_MARK_CLASS[tier];

  const segments = text.match(/[^.!?\n。！？]+[.!?\n。！？]*/g) || [text];
  if (segments.length <= 1) {
    if (isFormattingNoise(text)) return text;
    return <mark className={markClass}>{text}</mark>;
  }

  const queryTerms = query
    .toLowerCase()
    .split(/\s+/)
    .filter((t) => t.length > 2 || CJK_REGEX.test(t));

  let bestIdx = -1;
  let bestScore = -1;

  segments.forEach((segment, idx) => {
    if (isFormattingNoise(segment)) return;

    const sLower = segment.toLowerCase();
    const latinWords = (segment.match(/[a-zA-Z]{2,}/g) || []).length;
    const cjkChars = (
      segment.match(
        /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]/g,
      ) || []
    ).length;
    if (latinWords < 3 && cjkChars < 3) return; // Skip tiny fragments

    let score = 0;
    queryTerms.forEach((term) => {
      if (sLower.includes(term)) score += 5;
      else if (term.length >= 4 && sLower.includes(term.slice(0, 4)))
        score += 2;
    });

    score += Math.min(latinWords + cjkChars * 0.5, 15) * 0.2;

    if (score > bestScore) {
      bestScore = score;
      bestIdx = idx;
    }
  });

  if (bestIdx === -1) {
    bestIdx = segments.findIndex((s) => !isFormattingNoise(s));
  }

  if (bestIdx === -1) return text;

  return (
    <>
      {segments.map((s, idx) => {
        if (idx === bestIdx) {
          return (
            <mark key={`semantic-span-${idx}`} className={markClass}>
              {s}
            </mark>
          );
        }
        return <span key={`span-${idx}`}>{s}</span>;
      })}
    </>
  );
}

export function HighlightedText({
  highlights,
  fallbackText,
  className,
  isSemanticMatch,
  searchQuery,
  scoreTier,
  markClassName = DEFAULT_MARK_CLASS,
}: HighlightedTextProps) {
  const tier: SemanticTier = scoreTier ?? "high";

  if (!highlights || highlights.length === 0) {
    if (isSemanticMatch && searchQuery) {
      return (
        <span className={className}>
          {highlightSemanticSpan(fallbackText, searchQuery, tier)}
        </span>
      );
    }
    return <span className={className}>{fallbackText}</span>;
  }

  let fragmentId = 0;
  return (
    <span className={className}>
      {highlights.map((fragment, i) => {
        const key = `f${fragmentId++}`;
        return (
          <span key={key}>
            {i > 0 && (
              <span className="text-muted-foreground mx-1 select-none">…</span>
            )}
            {parseFragment(
              fragment,
              key,
              markClassName,
              isSemanticMatch ? tier : undefined,
            )}
          </span>
        );
      })}
    </span>
  );
}
