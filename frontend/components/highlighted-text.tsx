/**
 * Renders search highlight fragments returned by OpenSearch.
 *
 * OpenSearch wraps matched terms in `<mark>` tags inside plain text fragments.
 * This component converts those strings to React elements so the marks render
 * as highlighted spans instead of raw HTML.
 *
 * Falls back to the full `fallbackText` when no highlights are available
 * (pure semantic/KNN hits that had no keyword match).
 */

interface HighlightedTextProps {
  /** Highlight fragments from OpenSearch (may contain <mark> tags). */
  highlights: string[];
  /** Plain text shown when highlights is empty. */
  fallbackText: string;
  className?: string;
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
): React.ReactNode {
  // Split on <mark>…</mark> pairs, keeping the captured groups.
  const parts = fragment.split(/(<mark>.*?<\/mark>)/g);
  let partId = 0;
  return parts.map((part) => {
    // Use prefix + counter for unique keys (no array index)
    const key = `${keyPrefix}-p${partId++}`;
    if (part.startsWith("<mark>") && part.endsWith("</mark>")) {
      const inner = part.slice(6, -7); // strip <mark> and </mark>
      return (
        <mark key={key} className={markClassName}>
          {inner}
        </mark>
      );
    }
    return part ? <span key={key}>{part}</span> : null;
  });
}

export function HighlightedText({
  highlights,
  fallbackText,
  className,
  markClassName = DEFAULT_MARK_CLASS,
}: HighlightedTextProps) {
  if (!highlights || highlights.length === 0) {
    return <span className={className}>{fallbackText}</span>;
  }

  // Generate unique keys using a counter instead of array index
  let fragmentId = 0;
  return (
    <span className={className}>
      {highlights.map((fragment, i) => {
        const key = `f${fragmentId++}`;
        return (
          // Separate fragments with an ellipsis so the reader knows they are
          // non-contiguous excerpts from the full chunk text.
          <span key={key}>
            {i > 0 && (
              <span className="text-muted-foreground mx-1 select-none">…</span>
            )}
            {parseFragment(fragment, key, markClassName)}
          </span>
        );
      })}
    </span>
  );
}
