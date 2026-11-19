import { RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";

interface MessageActionsProps {
  trackFeedback: (feedback: "like" | "dislike") => void;
  onRetry?: () => void;
  disabled?: boolean;
}

const MessageActions = ({
  trackFeedback,
  onRetry,
  disabled,
}: MessageActionsProps) => {
  const [feedbackSelected, setFeedbackSelected] = useState<
    "like" | "dislike" | null
  >(null);

  const handleFeedback = (feedback: "like" | "dislike") => {
    if (feedbackSelected === feedback) return; // Prevent multiple tracking events for the same feedback
    trackFeedback(feedback);
    setFeedbackSelected(feedback);
  };

  return (
    <div className="flex space-x-2">
      {onRetry && (
        <Button
          variant="outline"
          size="icon"
          aria-label="Retry"
          onClick={onRetry}
          disabled={disabled}
        >
          <RotateCcw className="h-4 w-4" />
        </Button>
      )}
      <Button
        variant="outline"
        size="icon"
        aria-label="Like"
        aria-pressed={feedbackSelected === "like"}
        className={
          feedbackSelected !== "like"
            ? "text-muted-foreground hover:text-foreground"
            : ""
        }
        onClick={() => handleFeedback("like")}
      >
        <ThumbsUp
          className={`h-4 w-4 ${feedbackSelected === "like" ? "fill-current" : ""}`}
        />
      </Button>
      <Button
        variant="outline"
        size="icon"
        aria-label="Dislike"
        aria-pressed={feedbackSelected === "dislike"}
        className={
          feedbackSelected !== "dislike"
            ? "text-muted-foreground hover:text-foreground"
            : ""
        }
        onClick={() => handleFeedback("dislike")}
      >
        <ThumbsDown
          className={`h-4 w-4 ${feedbackSelected === "dislike" ? "fill-current" : ""}`}
        />
      </Button>
    </div>
  );
};

export default MessageActions;
