import { AnimatedProcessingIcon } from "./animated-processing-icon";

export type Status =
  | "processing"
  | "active"
  | "unavailable"
  | "hidden"
  | "sync";

interface StatusBadgeProps {
  status: Status;
  className?: string;
}

const statusConfig = {
  processing: {
    label: "Processing",
    className: "text-muted-foreground dark:text-muted-foreground ",
  },
  active: {
    label: "Active",
    className: "text-emerald-600 dark:text-emerald-400 ",
  },
  unavailable: {
    label: "Unavailable",
    className: "text-red-600 dark:text-red-400 ",
  },
  hidden: {
    label: "Hidden",
    className: "text-zinc-400 dark:text-zinc-500 ",
  },
  sync: {
    label: "Sync",
    className: "text-amber-700 dark:text-amber-300 underline",
  },
};

export const StatusBadge = ({ status, className }: StatusBadgeProps) => {
  const config = statusConfig[status];

  return (
    <div
      className={`inline-flex items-center gap-1 ${config.className} ${
        className || ""
      }`}
    >
      {status === "processing" && (
        <AnimatedProcessingIcon className="text-current mr-2" size={10} />
      )}
      {config.label}
    </div>
  );
};
