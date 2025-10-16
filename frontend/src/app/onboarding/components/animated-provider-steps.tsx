import { CheckIcon } from "lucide-react";
import { useEffect } from "react";
import { AnimatedProcessingIcon } from "@/components/ui/animated-processing-icon";
import { cn } from "@/lib/utils";

export function AnimatedProviderSteps({
  currentStep,
  setCurrentStep,
}: {
  currentStep: number;
  setCurrentStep: (step: number) => void;
}) {
  const steps = [
    "Setting up your model provider",
    "Defining schema",
    "Configuring Langflow",
    "Ingesting sample data",
  ];

  useEffect(() => {
    if (currentStep < steps.length - 1) {
      const interval = setInterval(() => {
        setCurrentStep(currentStep + 1);
      }, 1000);
      return () => clearInterval(interval);
    } else {
      const interval = setInterval(() => {
        setCurrentStep(currentStep + 1);
      }, 3000);
      return () => clearInterval(interval);
    }
  }, [currentStep, setCurrentStep]);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <div className={cn("transition-all duration-300", currentStep >= steps.length ? "w-3.5" : "w-2")}>
        {currentStep >= steps.length ? (
          <CheckIcon className="text-accent-emerald-foreground shrink-0 w-3.5 h-3.5" />
        ) : (
          <AnimatedProcessingIcon className="text-current shrink-0" />
        )}</div>

        <span className="text-mmd font-medium text-muted-foreground">
          {currentStep < steps.length ? "Thinking" : "Done"}
        </span>
      </div>
      {currentStep < steps.length && (
        <div className="flex items-center gap-5">
          <div className="w-px h-6 bg-border" />
          <span className="text-mmd font-medium text-primary">
            {steps[currentStep]}
          </span>
        </div>
      )}
    </div>
  );
}
