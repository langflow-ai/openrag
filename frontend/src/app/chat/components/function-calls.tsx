import { ChevronDown, ChevronRight, Settings } from "lucide-react";
import type { FunctionCall } from "../types";

interface FunctionCallsProps {
  functionCalls: FunctionCall[];
  messageIndex?: number;
  expandedFunctionCalls: Set<string>;
  onToggle: (functionCallId: string) => void;
}

export function FunctionCalls({
  functionCalls,
  messageIndex,
  expandedFunctionCalls,
  onToggle,
}: FunctionCallsProps) {
  if (!functionCalls || functionCalls.length === 0) return null;

  return (
    <div className="mb-3 space-y-2">
      {functionCalls.map((fc, index) => {
        const functionCallId = `${messageIndex || "streaming"}-${index}`;
        const isExpanded = expandedFunctionCalls.has(functionCallId);

        // Determine display name - show both name and type if available
        const displayName =
          fc.type && fc.type !== fc.name ? `${fc.name} (${fc.type})` : fc.name;

        return (
          <div
            key={index}
            className="rounded-lg bg-blue-500/10 border border-blue-500/20 p-3"
          >
            <div
              className="flex items-center gap-2 cursor-pointer hover:bg-blue-500/5 -m-3 p-3 rounded-lg transition-colors"
              onClick={() => onToggle(functionCallId)}
            >
              <Settings className="h-4 w-4 text-blue-400" />
              <span className="text-sm font-medium text-blue-400 flex-1">
                Function Call: {displayName}
              </span>
              {fc.id && (
                <span className="text-xs text-blue-300/70 font-mono">
                  {fc.id.substring(0, 8)}...
                </span>
              )}
              <div
                className={`px-2 py-1 rounded text-xs font-medium ${
                  fc.status === "completed"
                    ? "bg-green-500/20 text-green-400"
                    : fc.status === "error"
                      ? "bg-red-500/20 text-red-400"
                      : "bg-yellow-500/20 text-yellow-400"
                }`}
              >
                {fc.status}
              </div>
              {isExpanded ? (
                <ChevronDown className="h-4 w-4 text-blue-400" />
              ) : (
                <ChevronRight className="h-4 w-4 text-blue-400" />
              )}
            </div>

            {isExpanded && (
              <div className="mt-3 pt-3 border-t border-blue-500/20">
                {/* Show type information if available */}
                {fc.type && (
                  <div className="text-xs text-muted-foreground mb-3">
                    <span className="font-medium">Type:</span>
                    <span className="ml-2 px-2 py-1 bg-muted/30 rounded font-mono">
                      {fc.type}
                    </span>
                  </div>
                )}

                {/* Show ID if available */}
                {fc.id && (
                  <div className="text-xs text-muted-foreground mb-3">
                    <span className="font-medium">ID:</span>
                    <span className="ml-2 px-2 py-1 bg-muted/30 rounded font-mono">
                      {fc.id}
                    </span>
                  </div>
                )}

                {/* Show arguments - either completed or streaming */}
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

                {fc.result && (
                  <div className="text-xs text-muted-foreground">
                    <span className="font-medium">Result:</span>
                    {Array.isArray(fc.result) ? (
                      <div className="mt-1 space-y-2">
                        {(() => {
                          // Handle different result formats
                          let resultsToRender = fc.result;

                          // Check if this is function_call format with nested results
                          // Function call format: results = [{ results: [...] }]
                          // Tool call format: results = [{ text_key: ..., data: {...} }]
                          if (
                            fc.result.length > 0 &&
                            fc.result[0]?.results &&
                            Array.isArray(fc.result[0].results) &&
                            !fc.result[0].text_key
                          ) {
                            resultsToRender = fc.result[0].results;
                          }

                          type ToolResultItem = {
                            text_key?: string;
                            data?: { file_path?: string; text?: string };
                            filename?: string;
                            page?: number;
                            score?: number;
                            source_url?: string | null;
                            text?: string;
                          };
                          const items =
                            resultsToRender as unknown as ToolResultItem[];
                          return items.map((result, idx: number) => (
                            <div
                              key={idx}
                              className="p-2 bg-muted/30 rounded border border-muted/50"
                            >
                              {/* Handle tool_call format (file_path in data) */}
                              {result.data?.file_path && (
                                <div className="font-medium text-blue-400 mb-1 text-xs">
                                  📄 {result.data.file_path || "Unknown file"}
                                </div>
                              )}

                              {/* Handle function_call format (filename directly) */}
                              {result.filename && !result.data?.file_path && (
                                <div className="font-medium text-blue-400 mb-1 text-xs">
                                  📄 {result.filename}
                                  {result.page && ` (page ${result.page})`}
                                  {result.score && (
                                    <span className="ml-2 text-xs text-muted-foreground">
                                      Score: {result.score.toFixed(3)}
                                    </span>
                                  )}
                                </div>
                              )}

                              {/* Handle tool_call text format */}
                              {result.data?.text && (
                                <div className="text-xs text-foreground whitespace-pre-wrap max-h-32 overflow-y-auto">
                                  {result.data.text.length > 300
                                    ? result.data.text.substring(0, 300) + "..."
                                    : result.data.text}
                                </div>
                              )}

                              {/* Handle function_call text format */}
                              {result.text && !result.data?.text && (
                                <div className="text-xs text-foreground whitespace-pre-wrap max-h-32 overflow-y-auto">
                                  {result.text.length > 300
                                    ? result.text.substring(0, 300) + "..."
                                    : result.text}
                                </div>
                              )}

                              {/* Show additional metadata for function_call format */}
                              {result.source_url && (
                                <div className="text-xs text-muted-foreground mt-1">
                                  <a
                                    href={result.source_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-blue-400 hover:underline"
                                  >
                                    Source URL
                                  </a>
                                </div>
                              )}

                              {result.text_key && (
                                <div className="text-xs text-muted-foreground mt-1">
                                  Key: {result.text_key}
                                </div>
                              )}
                            </div>
                          ));
                        })()}
                        <div className="text-xs text-muted-foreground">
                          Found {(() => {
                            let resultsToCount = fc.result;
                            if (
                              fc.result.length > 0 &&
                              fc.result[0]?.results &&
                              Array.isArray(fc.result[0].results) &&
                              !fc.result[0].text_key
                            ) {
                              resultsToCount = fc.result[0].results;
                            }
                            return resultsToCount.length;
                          })()} result
                          {(() => {
                            let resultsToCount = fc.result;
                            if (
                              fc.result.length > 0 &&
                              fc.result[0]?.results &&
                              Array.isArray(fc.result[0].results) &&
                              !fc.result[0].text_key
                            ) {
                              resultsToCount = fc.result[0].results;
                            }
                            return resultsToCount.length !== 1 ? "s" : "";
                          })()}
                        </div>
                      </div>
                    ) : (
                      <pre className="mt-1 p-2 bg-muted/30 rounded text-xs overflow-x-auto">
                        {JSON.stringify(fc.result, null, 2)}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
