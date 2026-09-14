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
}

/**
 * Parse a single fragment string like "foo <mark>bar</mark> baz" into an
 * array of React nodes, converting `<mark>` elements to styled spans.
 */
function parseFragment(fragment: string): React.ReactNode {
  // Split on <mark>…</mark> pairs, keeping the captured groups.
  const parts = fragment.split(/(<mark>.*?<\/mark>)/g);
  return parts.map((part, index) => {
    // Use content + index for unique keys (handles duplicate content)
    if (part.startsWith("<mark>") && part.endsWith("</mark>")) {
      const inner = part.slice(6, -7); // strip <mark> and </mark>
      return (
        <mark
          key={`${part}-${index}`}
          className="bg-yellow-200 dark:bg-yellow-800 text-foreground rounded-[2px] px-[1px] not-italic"
        >
          {inner}
        </mark>
      );
    }
    return part ? <span key={`${part}-${index}`}>{part}</span> : null;
  });
}

export function HighlightedText({
  highlights,
  fallbackText,
  className,
}: HighlightedTextProps) {
  if (!highlights || highlights.length === 0) {
    return <span className={className}>{fallbackText}</span>;
  }

  return (
    <span className={className}>
      {highlights.map((fragment, i) => {
        // Use content + index for unique keys (handles repeated excerpts)
        return (
          // Separate fragments with an ellipsis so the reader knows they are
          // non-contiguous excerpts from the full chunk text.
          <span key={`${fragment}-${i}`}>
            {i > 0 && (
              <span className="text-muted-foreground mx-1 select-none">…</span>
            )}
            {parseFragment(fragment)}
          </span>
        );
      })}
    </span>
  );
}
