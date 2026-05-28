import { AlertCircle, CheckCircle, Clock, type LucideIcon } from "lucide-react";
import type { TaskFileStatusCategory } from "@/lib/task-utils";

export const CATEGORY_CHIPS: Array<{
  id: TaskFileStatusCategory;
  label: string;
  icon: LucideIcon;
  iconClassName: string;
}> = [
  {
    id: "completed",
    label: "Completed",
    icon: CheckCircle,
    iconClassName: "text-emerald-500",
  },
  {
    id: "system_error",
    label: "System error",
    icon: AlertCircle,
    iconClassName: "text-destructive",
  },
  {
    id: "indexing",
    label: "Indexing",
    icon: Clock,
    iconClassName: "text-muted-foreground",
  },
];
