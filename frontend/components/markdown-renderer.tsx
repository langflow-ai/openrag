import Markdown from "react-markdown";
import rehypeMathjax from "rehype-mathjax";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import CodeComponent from "./code-component";

type MarkdownRendererProps = {
  chatMessage: string;
  className?: string;
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
