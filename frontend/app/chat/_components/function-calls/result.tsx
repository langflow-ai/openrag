import type { FunctionCall as FunctionCallType } from "../../_types/types";

type ToolResultItem = {
  text_key?: string;
  data?: { file_path?: string; text?: string };
  filename?: string;
  page?: number;
  score?: number;
  source_url?: string | null;
  text?: string;
};

interface FunctionCallResultProps {
  result: FunctionCallType["result"];
}

export function FunctionCallResult({ result }: FunctionCallResultProps) {
  if (!Array.isArray(result)) {
    return (
      <div className="text-xs text-muted-foreground">
        <span className="font-medium">Result:</span>
        <pre className="mt-1 p-2 bg-muted/30 rounded text-xs overflow-x-auto">
          {JSON.stringify(result, null, 2)}
        </pre>
      </div>
    );
  }

  const isNestedFormat =
    result.length > 0 &&
    result[0]?.results &&
    Array.isArray(result[0].results) &&
    !result[0].text_key;
  const items = (
    isNestedFormat ? result[0].results : result
  ) as ToolResultItem[];

  return (
    <div className="text-xs text-muted-foreground">
      <span className="font-medium">Result:</span>
      <div className="mt-1 space-y-2">
        {items.map((item, idx) => (
          <div key={idx} className="fc-result p-2 bg-muted/30 rounded">
            {item.data?.file_path && (
              <div className="font-medium text-blue-400 mb-1 text-xs">
                📄 {item.data.file_path || "Unknown file"}
              </div>
            )}

            {item.filename && !item.data?.file_path && (
              <div className="font-medium text-blue-400 mb-1 text-xs">
                📄 {item.filename}
                {item.page && ` (page ${item.page})`}
                {item.score && (
                  <span className="ml-2 text-xs text-muted-foreground">
                    Score: {item.score.toFixed(3)}
                  </span>
                )}
              </div>
            )}

            {item.data?.text && (
              <div className="text-xs text-foreground whitespace-pre-wrap max-h-32 overflow-y-auto">
                {item.data.text.length > 300
                  ? item.data.text.substring(0, 300) + "..."
                  : item.data.text}
              </div>
            )}

            {item.text && !item.data?.text && (
              <div className="text-xs text-foreground whitespace-pre-wrap max-h-32 overflow-y-auto">
                {item.text.length > 300
                  ? item.text.substring(0, 300) + "..."
                  : item.text}
              </div>
            )}

            {item.source_url && (
              <div className="text-xs text-muted-foreground mt-1">
                <a
                  href={item.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-400 hover:underline"
                >
                  Source URL
                </a>
              </div>
            )}

            {item.text_key && (
              <div className="text-xs text-muted-foreground mt-1">
                Key: {item.text_key}
              </div>
            )}
          </div>
        ))}
        <div className="text-xs text-muted-foreground">
          Found {items.length} result{items.length !== 1 ? "s" : ""}
        </div>
      </div>
    </div>
  );
}
