import { ChevronDown, ChevronRight, Settings } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { FunctionCall as FunctionCallType } from "../../_types/types";
import { FunctionCallResult } from "./result";

interface FunctionCallProps {
  fc: FunctionCallType;
  isExpanded: boolean;
  onToggle: () => void;
  className?: string;
}

export function FunctionCall({
  fc,
  isExpanded,
  onToggle,
  className = "",
}: FunctionCallProps) {
  const displayName =
    fc.type && fc.type !== fc.name ? `${fc.name} (${fc.type})` : fc.name;

  return (
    <div
      className={`fc-card bg-blue-500/10 border-blue-500/20 p-3 ${className}`}
    >
      <div
        className="flex items-center gap-2 cursor-pointer hover:bg-blue-500/5 -m-3 p-3 rounded-lg transition-colors"
        onClick={onToggle}
      >
        <Settings className="h-4 w-4 text-blue-400" />
        <span className="text-sm font-medium text-blue-400 flex-1">
          Function Call: {displayName}
        </span>
        {fc.id && (
          <span className="text-xs text-blue-400 font-mono">
            {fc.id.substring(0, 8)}...
          </span>
        )}
        <Badge
          variant="outline"
          className={
            fc.status === "completed"
              ? "fc-status-completed border-green-500/40 bg-green-500/20 text-green-400"
              : fc.status === "error"
                ? "border-red-500/40 bg-red-500/20 text-red-400"
                : "border-yellow-500/40 bg-yellow-500/20 text-yellow-400"
          }
        >
          {fc.status}
        </Badge>
        {isExpanded ? (
          <ChevronDown className="h-4 w-4 text-blue-400" />
        ) : (
          <ChevronRight className="h-4 w-4 text-blue-400" />
        )}
      </div>

      {isExpanded && (
        <div className="mt-3 pt-3 border-t border-blue-500/20">
          {fc.type && (
            <div className="text-xs text-muted-foreground mb-3">
              <span className="font-medium">Type:</span>
              <span className="fc-value ml-2 px-2 py-1 bg-muted/30 rounded font-mono">
                {fc.type}
              </span>
            </div>
          )}

          {fc.id && (
            <div className="text-xs text-muted-foreground mb-3">
              <span className="font-medium">ID:</span>
              <span className="fc-value ml-2 px-2 py-1 bg-muted/30 rounded font-mono">
                {fc.id}
              </span>
            </div>
          )}

          {(fc.arguments || fc.argumentsString) && (
            <div className="text-xs text-muted-foreground mb-3">
              <span className="font-medium">Arguments:</span>
              <pre className="mt-1 p-2 bg-muted/30 rounded text-xs overflow-x-auto">
                {fc.arguments
                  ? JSON.stringify(fc.arguments, null, 2)
                  : fc.argumentsString || "..."}
              </pre>
            </div>
          )}

          {fc.result && <FunctionCallResult result={fc.result} />}
        </div>
      )}
    </div>
  );
}
