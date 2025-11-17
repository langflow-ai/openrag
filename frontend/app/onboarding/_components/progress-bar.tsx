import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ProgressBarProps {
  currentStep: number;
  totalSteps: number;
  onSkip?: () => void;
}

export function ProgressBar({
  currentStep,
  totalSteps,
  onSkip,
}: ProgressBarProps) {
  const progressPercentage = ((currentStep + 1) / totalSteps) * 100;

  return (
    <div className="w-full flex items-center px-6 gap-4">
      <div className="flex-1" />
      <div className="flex items-center gap-3">
        <div className="w-48 h-1 bg-background dark:bg-muted rounded-full overflow-hidden">
          <div
            className="h-full transition-all duration-300 ease-in-out"
            style={{
              width: `${progressPercentage}%`,
              background: "linear-gradient(to right, #773EFF, #22A7AF)",
            }}
          />
        </div>
        <span className="text-xs text-muted-foreground whitespace-nowrap">
          {currentStep + 1}/{totalSteps}
        </span>
      </div>
      <div className="flex-1 flex justify-end">
        {currentStep > 0 && onSkip && (
          <Button
            variant="link"
            size="sm"
            onClick={onSkip}
            className="flex items-center gap-2 text-mmd !text-placeholder-foreground hover:!text-foreground hover:!no-underline"
          >
            Skip overview
            <ArrowRight className="w-4 h-4" />
          </Button>
        )}
      </div>
    </div>
  );
}
