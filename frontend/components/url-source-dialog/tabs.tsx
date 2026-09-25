import { Check, RefreshCw } from "lucide-react";
import { KnowledgeUrlIcon } from "@/components/knowledge-url-icon";
import { cn } from "@/lib/utils";

export type UrlSourceDialogStep = 1 | 2;

export function UrlSourceDialogTabs({
  step,
  sourceComplete,
  onStepChange,
}: {
  step: UrlSourceDialogStep;
  sourceComplete: boolean;
  onStepChange(step: UrlSourceDialogStep): void;
}) {
  return (
    <div
      className="-mx-6 grid shrink-0 grid-cols-2 border-y"
      role="group"
      aria-label="Website connection steps"
    >
      <button
        type="button"
        aria-current={step === 1 ? "step" : undefined}
        onClick={() => onStepChange(1)}
        className={cn(
          "flex w-full items-center gap-3 px-4 py-4 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:underline focus-visible:underline-offset-4",
          step === 1 && "border-b-2 border-b-primary",
        )}
      >
        <span
          className={cn(
            "flex size-7 items-center justify-center rounded-full text-sm",
            step > 1 && sourceComplete
              ? "bg-green-500 text-white"
              : step === 1
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground",
          )}
        >
          {step > 1 && sourceComplete ? (
            <Check className="size-4" />
          ) : (
            <KnowledgeUrlIcon className="size-4" />
          )}
        </span>
        <span className="font-medium">Source &amp; scope</span>
      </button>
      <button
        type="button"
        aria-current={step === 2 ? "step" : undefined}
        onClick={() => onStepChange(2)}
        className={cn(
          "flex w-full items-center gap-3 border-l px-4 py-4 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:underline focus-visible:underline-offset-4",
          step === 2 && "border-b-2 border-b-primary",
        )}
      >
        <span
          className={cn(
            "flex size-7 items-center justify-center rounded-full text-sm",
            step === 2
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground",
          )}
        >
          <RefreshCw className="size-4" />
        </span>
        <span className="font-medium">Re-sync behavior</span>
      </button>
    </div>
  );
}
