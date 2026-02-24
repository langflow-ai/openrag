import { Zap } from "lucide-react";
import type { TokenUsage as TokenUsageType } from "../_types/types";

interface TokenUsageProps {
  usage: TokenUsageType;
}

export function TokenUsage({ usage }: TokenUsageProps) {
  // Guard against partial/malformed usage data
  if (typeof usage.input_tokens !== "number" || typeof usage.output_tokens !== "number") {
    return null;
  }

  return (
    <div className="flex items-center gap-2 mt-2 text-xs text-muted-foreground">
      <Zap className="h-3 w-3" />
      <span>
        {usage.input_tokens.toLocaleString()} in / {usage.output_tokens.toLocaleString()} out
        {usage.input_tokens_details?.cached_tokens ? (
          <span className="text-green-500 ml-1">
            ({usage.input_tokens_details.cached_tokens.toLocaleString()} cached)
          </span>
        ) : null}
      </span>
    </div>
  );
}
