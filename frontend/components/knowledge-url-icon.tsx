import { Globe } from "lucide-react";
import { cn } from "@/lib/utils";

/** The one URL glyph used in the source table, connector menu, and child view. */
export function KnowledgeUrlIcon({ className }: { className?: string }) {
  return <Globe className={cn("shrink-0", className)} />;
}
