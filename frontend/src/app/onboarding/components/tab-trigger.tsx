import AnimatedProcessingIcon from "@/components/ui/animated-processing-icon";
import { cn } from "@/lib/utils";

export function TabTrigger({
  children,
  selected,
  isLoading,
}: {
  children: React.ReactNode;
  selected: boolean;
  isLoading: boolean;
}) {
  return (
    <div className="flex flex-col relative items-start justify-between gap-4 h-full w-full">
      <div
        className={cn(
          "flex absolute items-center justify-center h-full w-full transition-opacity duration-200",
          isLoading && selected ? "opacity-100" : "opacity-0",
        )}
      >
        <AnimatedProcessingIcon className="text-current shrink-0 h-10 w-10" />
      </div>
      <div
        className={cn(
          "flex flex-col items-start justify-between gap-4 h-full w-full transition-opacity duration-200",
          isLoading && selected ? "opacity-0" : "opacity-100",
        )}
      >
        {children}
      </div>
    </div>
  );
}
