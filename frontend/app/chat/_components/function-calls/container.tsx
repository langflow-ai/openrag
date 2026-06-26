import { useState } from "react";
import type { FunctionCall as FunctionCallType } from "../../_types/types";
import { FunctionCall } from "./call";
import { FunctionCallsHeader } from "./header";

interface FunctionCallsContainerProps {
  functionCalls: FunctionCallType[];
  messageIndex?: number;
  expandedFunctionCalls: Set<string>;
  onToggle: (functionCallId: string) => void;
  isStreaming?: boolean;
}

export function FunctionCallsContainer({
  functionCalls,
  messageIndex,
  expandedFunctionCalls,
  onToggle,
  isStreaming = false,
}: FunctionCallsContainerProps) {
  const [isGroupExpanded, setIsGroupExpanded] = useState(isStreaming);

  if (!functionCalls || functionCalls.length === 0) return null;

  const showGroupHeader = functionCalls.length > 1;
  const uniqueToolCount = new Set(functionCalls.map((fc) => fc.name)).size;
  const showCards = !showGroupHeader || isGroupExpanded;

  return (
    <div className="mb-3">
      {showGroupHeader && (
        <FunctionCallsHeader
          uniqueToolCount={uniqueToolCount}
          totalCalls={functionCalls.length}
          isExpanded={isGroupExpanded}
          onToggle={() => setIsGroupExpanded((v) => !v)}
        />
      )}
      {showCards &&
        functionCalls.map((fc, index) => {
          const functionCallId = `${messageIndex || "streaming"}-${index}`;
          const isExpanded = expandedFunctionCalls.has(functionCallId);
          const isFirst = index === 0;
          const isLast = index === functionCalls.length - 1;
          const topRounded = isFirst && !showGroupHeader;
          const bottomRounded = isLast;
          const radius = `${topRounded ? "rounded-t-lg" : ""} ${
            bottomRounded ? "rounded-b-lg" : ""
          }`.trim();
          const border =
            isFirst && !showGroupHeader ? "border" : "border border-t-0";

          return (
            <FunctionCall
              key={index}
              fc={fc}
              isExpanded={isExpanded}
              onToggle={() => onToggle(functionCallId)}
              className={`${border} ${radius}`}
            />
          );
        })}
    </div>
  );
}
