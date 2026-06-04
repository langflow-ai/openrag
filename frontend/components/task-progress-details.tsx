import { Circle } from "lucide-react";
import { cn } from "@/lib/utils";

export interface TaskProgressDetailed {
  total: number;
  processed: number;
  successful: number;
  failed: number;
  running: number;
  pending: number;
  remaining: number;
}

interface TaskProgressDetailsProps {
  detailed: TaskProgressDetailed;
  isCloudBrand: boolean;
}

const PROGRESS_STATS = [
  {
    key: "successful" as const,
    label: "Complete",
    colorClass: "text-green-500",
  },
  {
    key: "failed" as const,
    label: "Failed",
    colorClass: "text-red-500",
  },
  {
    key: "running" as const,
    label: "Running",
    colorClass: "text-blue-500",
  },
  {
    key: "pending" as const,
    label: "Pending",
    colorClass: "text-yellow-500",
  },
] as const;

export function TaskProgressDetails({
  detailed,
  isCloudBrand,
}: TaskProgressDetailsProps) {
  return (
    <div className={cn("grid grid-cols-2", isCloudBrand ? "gap-2" : "gap-3")}>
      {PROGRESS_STATS.map(({ key, label, colorClass }) => (
        <div
          key={key}
          className={cn(
            "flex w-full shrink-0 flex-col items-start gap-3 pt-0.5 pr-1.5 pb-0.5 pl-1 text-xs",
            isCloudBrand
              ? "col-span-1 row-span-1 justify-center self-stretch justify-self-stretch rounded-none bg-border"
              : "min-h-header rounded-md bg-muted",
          )}
        >
          <span
            className={cn(
              "block pt-1.5 px-1.5 pb-0 text-base font-semibold tabular-nums leading-none",
              isCloudBrand ? "text-muted-foreground" : "text-foreground",
            )}
          >
            {detailed[key]}
          </span>
          <span className="inline-flex items-center gap-1 px-1.5 pb-1.5">
            <Circle className={cn("size-2 fill-current", colorClass)} />
            <span
              className={
                isCloudBrand ? "text-placeholder" : "text-muted-foreground"
              }
            >
              {label}
            </span>
          </span>
        </div>
      ))}
    </div>
  );
}
