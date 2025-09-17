import { Check, ChevronDown, ChevronUp, Copy } from "lucide-react";
import { memo, useMemo, useState } from "react";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";

type CodeComponentProps = {
  code: string;
  language: string;
};

const CodeComponent = memo(function CodeComponent({
  code,
  language,
}: CodeComponentProps) {
  const [isCopied, setIsCopied] = useState<boolean>(false);
  const [isExpanded, setIsExpanded] = useState<boolean>(false);

  const { lineCount, shouldCollapse, previewCode } = useMemo(() => {
    const lines = code.split("\n");
    const lineCount = lines.length;
    const shouldCollapse = lineCount > 10;
    const previewCode = shouldCollapse
      ? lines.slice(0, 8).join("\n") + "\n..."
      : code;

    return { lineCount, shouldCollapse, previewCode };
  }, [code]);

  const copyToClipboard = () => {
    if (!navigator.clipboard || !navigator.clipboard.writeText) {
      return;
    }

    navigator.clipboard.writeText(code).then(() => {
      setIsCopied(true);

      setTimeout(() => {
        setIsCopied(false);
      }, 2000);
    });
  };

  const displayCode = shouldCollapse && !isExpanded ? previewCode : code;
  const maxHeight = isExpanded ? "600px" : shouldCollapse ? "200px" : "400px";

  return (
    <div
      className="mt-2 mb-4 relative flex w-full max-w-full flex-col overflow-hidden rounded-lg border border-border bg-muted/30 text-left"
      data-testid="chat-code-tab"
    >
      {/* Header with language and controls */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-muted/50">
        <div className="flex items-center gap-2">
          {language && (
            <Badge variant="secondary" className="text-xs font-mono">
              {language.toLowerCase()}
            </Badge>
          )}
          <span className="text-xs text-muted-foreground">
            {lineCount} line{lineCount !== 1 ? "s" : ""}
          </span>
        </div>

        <div className="flex items-center gap-1">
          {shouldCollapse && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setIsExpanded(!isExpanded)}
            >
              {isExpanded ? (
                <>
                  <ChevronUp className="h-3 w-3 mr-1" />
                  Collapse
                </>
              ) : (
                <>
                  <ChevronDown className="h-3 w-3 mr-1" />
                  Expand
                </>
              )}
            </Button>
          )}

          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-muted-foreground hover:text-foreground"
            data-testid="copy-code-button"
            onClick={copyToClipboard}
          >
            {isCopied ? (
              <>
                <Check className="h-3 w-3 mr-1" />
                Copied
              </>
            ) : (
              <>
                <Copy className="h-3 w-3 mr-1" />
                Copy
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Code content */}
      <div className="relative overflow-hidden" style={{ maxHeight }}>
        <div
          className="overflow-auto max-h-full"
          style={{
            maxHeight: maxHeight,
            scrollBehavior: "auto",
            overscrollBehavior: "auto",
            scrollbarGutter: "stable",
            backgroundColor: "hsl(var(--muted))",
          }}
        >
          <div
            className="text-sm font-mono leading-relaxed whitespace-pre-wrap text-foreground"
            style={{
              fontSize: "13px",
              lineHeight: "1.6",
              fontFamily:
                'ui-monospace, SFMono-Regular, "SF Mono", Consolas, "Liberation Mono", Menlo, monospace',
              wordWrap: "break-word",
              overflowWrap: "anywhere",
              whiteSpace: "pre-wrap",
              overflowAnchor: "none",
              padding: "12px 16px 12px 16px",
              margin: "0",
              backgroundColor: "hsl(var(--muted))",
              color: "hsl(var(--foreground))",
            }}
          >
            {displayCode}
          </div>
        </div>

        {/* Fade overlay for collapsed state */}
        {shouldCollapse && !isExpanded && (
          <div className="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-muted/30 to-transparent pointer-events-none" />
        )}
      </div>
    </div>
  );
});

export default CodeComponent;
