import dynamic from "next/dynamic";
import Markdown from "react-markdown";
import rehypeMathjax from "rehype-mathjax";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import type { ToolCallResult } from "@/app/chat/_types/types";
import { cn } from "@/lib/utils";

const CodeComponent = dynamic(() => import("./code-component"), {
  ssr: false,
  loading: () => (
    <div className="mt-2 h-12 animate-pulse rounded-md bg-muted" />
  ),
});

type MarkdownRendererProps = {
  chatMessage: string;
  className?: string;
  onCitationClick?: (index: number, anchorElement: HTMLElement) => void;
};

// Helper to extract a clean chunk index from chunk_id (0-based in ID, 1-based output)
export const getChunkNumber = (chunkId: string | undefined): number | null => {
  if (!chunkId) return null;
  const parts = chunkId.split("_");
  if (parts.length > 1) {
    const lastPart = parts[parts.length - 1];
    if (/^\d+$/.test(lastPart)) {
      return parseInt(lastPart, 10) + 1;
    }
  }
  return null;
};

export interface CitedSource {
  item: ToolCallResult;
  index: number;
}

export const preprocessCitations = (
  text: string,
  sources: ToolCallResult[] | undefined,
): { text: string; citedSources: CitedSource[] } => {
  if (!sources || sources.length === 0) {
    return { text, citedSources: [] };
  }

  const citedSourcesMap = new Map<string, number>();
  const citedSourcesList: CitedSource[] = [];
  let nextIndex = 1;

  // Patterns: (Source: chunk_id) or [Source: chunk_id]
  const regex = /\[Source:\s*([^\]]+)\]|\(Source:\s*([^)]+)\)/g;

  const processedText = text.replace(regex, (match, p1, p2) => {
    const rawIds = p1 || p2;
    if (!rawIds) return match;

    // Split by comma in case LLM grouped multiple chunk citations
    const ids = rawIds.split(",").map((id: string) => id.trim());
    const replacementBadges: string[] = [];

    for (const rawId of ids) {
      // Find matching source by chunk_id, id, file_path, or filename
      const foundSource = sources.find(
        (s) =>
          s.chunk_id === rawId ||
          s.id === rawId ||
          s.data?.file_path === rawId ||
          s.filename === rawId,
      );

      if (foundSource) {
        const uniqueKey = (foundSource.chunk_id ||
          foundSource.id ||
          foundSource.filename ||
          JSON.stringify(foundSource)) as string;

        let index = citedSourcesMap.get(uniqueKey);
        if (index === undefined) {
          index = nextIndex++;
          citedSourcesMap.set(uniqueKey, index);
          citedSourcesList.push({ item: foundSource, index });
        }
        replacementBadges.push(`[\\[${index}\\]](#citation-${index})`);
      }
    }

    if (replacementBadges.length > 0) {
      return replacementBadges.join("");
    }

    return match;
  });

  return { text: processedText, citedSources: citedSourcesList };
};

const preprocessChatMessage = (text: string): string => {
  // Handle <think> tags
  let processed = text
    .replace(/<think>/g, "`<think>`")
    .replace(/<\/think>/g, "`</think>`");

  // Clean up tables if present
  if (isMarkdownTable(processed)) {
    processed = cleanupTableEmptyCells(processed);
  }

  return processed;
};

export const isMarkdownTable = (text: string): boolean => {
  if (!text?.trim()) return false;

  // Single regex to detect markdown table with header separator
  return /\|.*\|.*\n\s*\|[\s\-:]+\|/m.test(text);
};

export const cleanupTableEmptyCells = (text: string): string => {
  return text
    .split("\n")
    .filter((line) => {
      const trimmed = line.trim();

      // Keep non-table lines
      if (!trimmed.includes("|")) return true;

      // Keep separator rows (contain only |, -, :, spaces)
      if (/^\|[\s\-:]+\|$/.test(trimmed)) return true;

      // For data rows, check if any cell has content
      const cells = trimmed.split("|").slice(1, -1); // Remove delimiter cells
      return cells.some((cell) => cell.trim() !== "");
    })
    .join("\n");
};

export const MarkdownRenderer = ({
  chatMessage,
  className,
  onCitationClick,
}: MarkdownRendererProps) => {
  // Process the chat message to handle <think> tags and clean up tables
  const processedChatMessage = preprocessChatMessage(chatMessage);

  return (
    <div
      className={cn(
        "markdown prose flex w-full max-w-full flex-col items-baseline text-base font-normal word-break-break-word dark:prose-invert",
        !chatMessage ? "text-muted-foreground" : "text-primary",
        className,
      )}
    >
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeMathjax, rehypeRaw]}
        urlTransform={(url) => url}
        components={{
          p({ node, ...props }) {
            return (
              <p className="w-fit max-w-full first:mt-0 last:mb-0 my-2">
                {props.children}
              </p>
            );
          },
          ol({ node, ...props }) {
            return <ol className="max-w-full">{props.children}</ol>;
          },
          strong({ node, ...props }) {
            return <strong className="font-bold">{props.children}</strong>;
          },
          h1({ node, ...props }) {
            return <h1 className="mb-6 mt-4">{props.children}</h1>;
          },
          h2({ node, ...props }) {
            return <h2 className="mb-4 mt-4">{props.children}</h2>;
          },
          h3({ node, ...props }) {
            return <h3 className="mb-2 mt-4">{props.children}</h3>;
          },
          hr() {
            return <hr className="w-full mt-4 mb-8" />;
          },
          ul({ node, ...props }) {
            return <ul className="max-w-full mb-2">{props.children}</ul>;
          },
          pre({ node, ...props }) {
            return <>{props.children}</>;
          },
          table: ({ node, ...props }) => {
            return (
              <div className="max-w-full overflow-hidden rounded-md border bg-muted">
                <div className="max-h-[600px] w-full overflow-auto p-4">
                  <table className="!my-0 w-full">{props.children}</table>
                </div>
              </div>
            );
          },
          a({ node, ...props }) {
            const href = props.href || "";
            if (href.startsWith("#citation-")) {
              const index = parseInt(href.replace("#citation-", ""), 10);
              return (
                <button
                  type="button"
                  onClick={(event) =>
                    onCitationClick?.(index, event.currentTarget)
                  }
                  className="inline-flex items-center justify-center mx-0.5 px-1 py-px text-[10px] font-bold text-violet-300 bg-violet-950/60 border border-violet-800/60 rounded hover:bg-violet-900/85 transition-all cursor-pointer select-none align-baseline transform translate-y-[-2px] shadow-sm shadow-violet-950/20"
                >
                  {props.children}
                </button>
              );
            }
            return (
              <a {...props} target="_blank" rel="noopener noreferrer">
                {props.children}
              </a>
            );
          },

          code(props) {
            const { children, className, ...rest } = props;
            let content = children as string;
            if (
              Array.isArray(children) &&
              children.length === 1 &&
              typeof children[0] === "string"
            ) {
              content = children[0] as string;
            }
            if (typeof content === "string") {
              if (content.length) {
                if (content[0] === "▍") {
                  return <span className="form-modal-markdown-span"></span>;
                }

                // Specifically handle <think> tags that were wrapped in backticks
                if (content === "<think>" || content === "</think>") {
                  return <span>{content}</span>;
                }
              }

              const match = /language-(\w+)/.exec(className || "");
              const isInline = !className?.startsWith("language-");

              return !isInline ? (
                <CodeComponent
                  language={(match && match[1]) || ""}
                  code={String(content).replace(/\n$/, "")}
                />
              ) : (
                <code className={className} {...rest}>
                  {content}
                </code>
              );
            }
          },
        }}
      >
        {processedChatMessage}
      </Markdown>
    </div>
  );
};
