type SemanticTier = "high" | "medium" | "low";

// indigo / purple / violet — mirrors badge colours in file-chunks-panel and page.
const SEMANTIC_MARK_CLASS: Record<SemanticTier, string> = {
  high: "bg-indigo-100 dark:bg-indigo-950/70 text-indigo-900 dark:text-indigo-100 border-b-[3px] border-indigo-500 dark:border-indigo-400 rounded-[2px] px-[2px] font-medium not-italic",
  medium:
    "bg-purple-100 dark:bg-purple-950/60 text-purple-900 dark:text-purple-100 border-b-2 border-purple-500 dark:border-purple-400 rounded-[2px] px-[2px] not-italic",
  low: "bg-violet-50 dark:bg-violet-950/40 text-violet-800 dark:text-violet-200 border-b border-violet-400 dark:border-violet-500 rounded-[2px] px-[2px] not-italic",
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
}

function parseFragment(
  fragment: string,
  keyPrefix: string,
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
            semanticTier
              ? SEMANTIC_MARK_CLASS[semanticTier]
              : "bg-yellow-200 dark:bg-yellow-800 text-foreground rounded-[2px] px-[1px] not-italic"
          }
        >
          {inner}
        </mark>
      );
    }
    return part ? <span key={key}>{part}</span> : null;
  });
}

function isFormattingNoise(s: string): boolean {
  const trimmed = s.trim();
  if (!trimmed || trimmed.length < 4) return true;
  if (new RegExp("^\\|?[\\s|:\\-]+\\|?$").test(trimmed)) return true;
  if (/^[-*=_]{3,}$/.test(trimmed)) return true;
  if (/^`{3,}/.test(trimmed)) return true;
  if (/^#{1,6}\s*$/.test(trimmed)) return true;
  if (!/[a-zA-Z]{3,}/.test(trimmed)) return true;
  return false;
}

function highlightSemanticSpan(
  text: string,
  query?: string,
  tier: SemanticTier = "high",
): React.ReactNode {
  if (!text || !query?.trim()) return text;

  const markClass = SEMANTIC_MARK_CLASS[tier];

  const segments = text.match(/[^.!?\n]+[.!?\n]*/g) || [text];
  if (segments.length <= 1) {
    if (isFormattingNoise(text)) return text;
    return <mark className={markClass}>{text}</mark>;
  }

  const queryTerms = query
    .toLowerCase()
    .split(/\s+/)
    .filter((t) => t.length > 2);

  let bestIdx = -1;
  let bestScore = -1;

  segments.forEach((segment, idx) => {
    if (isFormattingNoise(segment)) return;

    const sLower = segment.toLowerCase();
    const wordCount = (segment.match(/[a-zA-Z]{2,}/g) || []).length;
    if (wordCount < 3) return; // Skip tiny fragments

    let score = 0;
    queryTerms.forEach((term) => {
      if (sLower.includes(term)) score += 5;
      else if (term.length >= 4 && sLower.includes(term.slice(0, 4)))
        score += 2;
    });

    score += Math.min(wordCount, 15) * 0.2;

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
            {parseFragment(fragment, key, isSemanticMatch ? tier : undefined)}
          </span>
        );
      })}
    </span>
  );
}
