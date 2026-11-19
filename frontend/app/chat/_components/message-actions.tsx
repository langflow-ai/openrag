import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useEffect, useState } from "react";
import {
  type FeedbackRating,
  useCanonicalMessageFeedback,
  useMessageFeedbackMutation,
} from "@/app/api/mutations/useMessageFeedbackMutation";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { MessageFeedback } from "../_types/types";

const MAX_COMMENT = 2000;

interface MessageActionsProps {
  /** Analytics only; never receives comments or answer content. */
  trackFeedback: (feedback: "like" | "dislike") => void;
  conversationId?: string;
  messageId?: string;
  feedback?: MessageFeedback | null;
}

const MessageActions = ({
  trackFeedback,
  conversationId,
  messageId,
  feedback: restored,
}: MessageActionsProps) => {
  const canPersist = Boolean(conversationId && messageId);
  const cached = useCanonicalMessageFeedback(
    conversationId,
    messageId,
    restored,
  );
  const mutation = useMessageFeedbackMutation();
  // The server-confirmed result of this component's own save wins over an
  // older cached/history value (e.g. if identity resolved after the click).
  const canonical =
    mutation.data &&
    (!cached?.updated_at || mutation.data.updated_at >= cached.updated_at)
      ? mutation.data
      : cached;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    if (!editing) setDraft(canonical?.comment ?? "");
  }, [canonical?.comment, editing]);

  if (!canPersist) return null;

  const pending = mutation.isPending;
  const selected: FeedbackRating | null = canonical?.rating ?? null;

  const save = (
    rating: FeedbackRating,
    comment: string | null,
    closeEditor = false,
  ) => {
    if (pending || !conversationId || !messageId) return;
    mutation.mutate(
      { conversationId, messageId, rating, comment },
      {
        onSuccess: () => {
          if (closeEditor) setEditing(false);
        },
      },
    );
  };

  const choose = (rating: FeedbackRating) => {
    if (pending || selected === rating) return;
    trackFeedback(rating === "up" ? "like" : "dislike");
    // A rating change keeps any existing comment (full-value replace).
    save(rating, canonical?.comment ?? null);
    if (rating === "down") setEditing(true);
  };

  const retry = () => {
    const vars = mutation.variables;
    if (vars) save(vars.rating, vars.comment);
  };

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex space-x-2">
        <Button
          variant="outline"
          size="icon"
          aria-label="Like"
          aria-pressed={selected === "up"}
          disabled={pending}
          className={
            selected !== "up"
              ? "text-muted-foreground hover:text-foreground"
              : ""
          }
          onClick={() => choose("up")}
        >
          <ThumbsUp
            className={`h-4 w-4 ${selected === "up" ? "fill-current" : ""}`}
          />
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label="Dislike"
          aria-pressed={selected === "down"}
          disabled={pending}
          className={
            selected !== "down"
              ? "text-muted-foreground hover:text-foreground"
              : ""
          }
          onClick={() => choose("down")}
        >
          <ThumbsDown
            className={`h-4 w-4 ${selected === "down" ? "fill-current" : ""}`}
          />
        </Button>
        {selected && !editing && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setDraft(canonical?.comment ?? "");
              setEditing(true);
            }}
          >
            {canonical?.comment ? "Edit comment" : "Add comment"}
          </Button>
        )}
      </div>
      {pending && (
        <p role="status" className="text-xs text-muted-foreground">
          Saving feedback…
        </p>
      )}
      {mutation.isError && !pending && (
        <p role="alert" className="text-xs text-destructive">
          Couldn’t save your feedback.{" "}
          <button type="button" className="underline" onClick={retry}>
            Retry
          </button>
        </p>
      )}
      {editing && selected && (
        <div className="flex w-72 flex-col gap-2">
          <Textarea
            aria-label="Feedback comment"
            value={draft}
            disabled={pending}
            maxLength={MAX_COMMENT}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Optional: tell us more"
          />
          <div className="flex justify-end gap-2">
            {/* Cancelling never discards the vote that is already recorded. */}
            <Button
              variant="ghost"
              size="sm"
              disabled={pending}
              onClick={() => {
                setEditing(false);
                setDraft(canonical?.comment ?? "");
              }}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={pending}
              onClick={() => save(selected, draft.trim() ? draft : null, true)}
            >
              Save comment
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};

export default MessageActions;
