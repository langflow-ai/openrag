/* ******************************************************************************
 * IBM Confidential
 *
 * OCO Source Materials
 *
 *  Copyright IBM Corp. 2026  All Rights Reserved.
 *
 * The source code for this program is not published or otherwise divested
 * of its trade secrets, irrespective of what has been deposited with
 * the U.S. Copyright Office.
 ****************************************************************************** */

import { Zap } from "lucide-react";
import type { TokenUsage as TokenUsageType } from "../_types/types";

interface TokenUsageProps {
  usage: TokenUsageType;
}

export function TokenUsage({ usage }: TokenUsageProps) {
  // Guard against partial/malformed usage data
  if (
    typeof usage.input_tokens !== "number" ||
    typeof usage.output_tokens !== "number"
  ) {
    return null;
  }

  return (
    <div className="flex items-center gap-2 mt-2 text-xs text-muted-foreground">
      <Zap className="h-3 w-3" />
      <span>
        {usage.input_tokens.toLocaleString()} in /{" "}
        {usage.output_tokens.toLocaleString()} out
        {usage.input_tokens_details?.cached_tokens ? (
          <span className="text-green-500 ml-1">
            ({usage.input_tokens_details.cached_tokens.toLocaleString()} cached)
          </span>
        ) : null}
      </span>
    </div>
  );
}
