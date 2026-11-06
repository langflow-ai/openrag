import { Eye, EyeOff } from "lucide-react";

interface LowRelevanceBannerProps {
  showingAll: boolean;
  /** Text shown while low-relevance items are hidden. */
  hiddenMessage: string;
  /** Text shown while low-relevance items are visible. */
  shownMessage: string;
  onToggle: () => void;
}

export function LowRelevanceBanner({
  showingAll,
  hiddenMessage,
  shownMessage,
  onToggle,
}: LowRelevanceBannerProps) {
  return (
    <button
      type="button"
      className="flex w-full items-center gap-2 rounded-md border border-border/50 bg-muted/60 px-3 py-2 text-xs text-muted-foreground hover:bg-muted transition-colors"
      onClick={onToggle}
    >
      {showingAll ? (
        <Eye className="h-3.5 w-3.5 shrink-0" />
      ) : (
        <EyeOff className="h-3.5 w-3.5 shrink-0" />
      )}
      <span className="flex-1 text-left">
        {showingAll ? shownMessage : hiddenMessage}
      </span>
      <span className="flex items-center gap-1 font-medium text-foreground">
        {showingAll ? (
          <>
            <EyeOff className="h-3 w-3" />
            Hide low-relevance
          </>
        ) : (
          <>
            <Eye className="h-3 w-3" />
            Show all
          </>
        )}
      </span>
    </button>
  );
}
