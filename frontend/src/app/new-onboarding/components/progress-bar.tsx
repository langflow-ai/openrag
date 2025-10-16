interface ProgressBarProps {
  currentStep: number;
  totalSteps: number;
}

export function ProgressBar({ currentStep, totalSteps }: ProgressBarProps) {
  const progressPercentage = ((currentStep + 1) / totalSteps) * 100;

  return (
    <div className="w-full">
      <div className="flex items-center max-w-48 mx-auto gap-3">
        <div className="flex-1 h-1 bg-background rounded-full overflow-hidden">
          <div
            className="h-full transition-all duration-300 ease-in-out"
            style={{
              width: `${progressPercentage}%`,
              background: 'linear-gradient(to right, #818CF8, #F472B6)'
            }}
          />
        </div>
        <span className="text-xs text-muted-foreground whitespace-nowrap">
          {currentStep + 1}/{totalSteps}
        </span>
      </div>
    </div>
  );
}
