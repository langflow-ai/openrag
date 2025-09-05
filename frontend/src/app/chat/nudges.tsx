export default function Nudges({
  nudges,
  handleSuggestionClick,
}: {
  nudges: string[];
  handleSuggestionClick: (suggestion: string) => void;
}) {
  return (
    <div className="flex-shrink-0 px-6 pt-4 flex justify-center">
      <div className="w-full max-w-[75%] relative">
        <div className="flex gap-3 justify-start overflow-x-auto scrollbar-hide">
          {nudges.map((suggestion: string, index: number) => (
            <button
              key={index}
              onClick={() => handleSuggestionClick(suggestion)}
              className="px-2 py-1.5 bg-muted hover:bg-muted/50 rounded-lg text-sm text-placeholder-foreground hover:text-foreground transition-colors whitespace-nowrap"
            >
              {suggestion}
            </button>
          ))}
        </div>
        {/* Fade out gradient on the right */}
        <div className="absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-background to-transparent pointer-events-none"></div>
      </div>
    </div>
  );
}
