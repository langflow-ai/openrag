import { cn } from "@/lib/utils";
import { useMemo } from "react";
import Markdown from "react-markdown";
import rehypeMathjax from "rehype-mathjax";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import CodeComponent from "./code-component";

type MarkdownRendererProps = {
  chatMessage: string;
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

export const MarkdownRenderer = ({ chatMessage }: MarkdownRendererProps) => {
  // Process the chat message to handle <think> tags and clean up tables
  const processedChatMessage = preprocessChatMessage(chatMessage);

  // Memoize the components object to prevent CodeComponent recreation
  const markdownComponents = useMemo(
    () => ({
      p({ node, ...props }: { node?: any; [key: string]: any }) {
        return (
          <p className="leading-relaxed mb-2 last:mb-0">{props.children}</p>
        );
      },
      ol({ node, ...props }: { node?: any; [key: string]: any }) {
        return <ol className="max-w-full space-y-1">{props.children}</ol>;
      },
      ul({ node, ...props }: { node?: any; [key: string]: any }) {
        return <ul className="max-w-full space-y-1">{props.children}</ul>;
      },
      li({ node, ...props }: { node?: any; [key: string]: any }) {
        return <li className="leading-relaxed">{props.children}</li>;
      },
      h1({ node, ...props }: { node?: any; [key: string]: any }) {
        return (
          <h1 className="text-2xl font-semibold mb-4 mt-6 first:mt-0">
            {props.children}
          </h1>
        );
      },
      h2({ node, ...props }: { node?: any; [key: string]: any }) {
        return (
          <h2 className="text-xl font-semibold mb-3 mt-5 first:mt-0">
            {props.children}
          </h2>
        );
      },
      h3({ node, ...props }: { node?: any; [key: string]: any }) {
        return (
          <h3 className="text-lg font-semibold mb-2 mt-4 first:mt-0">
            {props.children}
          </h3>
        );
      },
      h4({ node, ...props }: { node?: any; [key: string]: any }) {
        return (
          <h4 className="text-base font-semibold mb-2 mt-3 first:mt-0">
            {props.children}
          </h4>
        );
      },
      hr({ node, ...props }: { node?: any; [key: string]: any }) {
        return <hr className="w-full my-6 border-border" />;
      },
      blockquote({ node, ...props }: { node?: any; [key: string]: any }) {
        return (
          <blockquote className="border-l-4 border-primary/30 bg-muted/50 px-4 py-3 my-4 rounded-r-md italic">
            {props.children}
          </blockquote>
        );
      },
      pre({ node, ...props }: { node?: any; [key: string]: any }) {
        return <>{props.children}</>;
      },
      table: ({ node, ...props }: { node?: any; [key: string]: any }) => {
        return (
          <div className="my-6 max-w-full overflow-hidden rounded-lg border border-border bg-muted/30">
            <div className="max-h-[600px] w-full overflow-auto">
              <table className="w-full text-sm">{props.children}</table>
            </div>
          </div>
        );
      },
      thead: ({ node, ...props }: { node?: any; [key: string]: any }) => {
        return (
          <thead className="bg-muted/70 border-b border-border">
            {props.children}
          </thead>
        );
      },
      tbody: ({ node, ...props }: { node?: any; [key: string]: any }) => {
        return (
          <tbody className="divide-y divide-border">{props.children}</tbody>
        );
      },
      th: ({ node, ...props }: { node?: any; [key: string]: any }) => {
        return (
          <th className="px-4 py-3 text-left font-medium text-foreground">
            {props.children}
          </th>
        );
      },
      td: ({ node, ...props }: { node?: any; [key: string]: any }) => {
        return (
          <td className="px-4 py-3 text-muted-foreground">{props.children}</td>
        );
      },
      code: ({
        node,
        className,
        inline,
        children,
        ...props
      }: {
        node?: any;
        [key: string]: any;
      }) => {
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
              return (
                <span className="text-muted-foreground font-mono text-sm">
                  {content}
                </span>
              );
            }
          }

          const match = /language-(\w+)/.exec(className || "");

          return !inline ? (
            <CodeComponent
              key={`${content.slice(0, 50)}-${(match && match[1]) || ""}`}
              language={(match && match[1]) || ""}
              code={String(content).replace(/\n$/, "")}
            />
          ) : (
            <code
              className="bg-muted/60 text-foreground px-1.5 py-0.5 rounded text-sm font-mono border border-border/50"
              {...props}
            >
              {content}
            </code>
          );
        }
      },
    }),
    []
  );

  return (
    <div
      className={cn(
        "markdown prose flex w-full max-w-full flex-col items-baseline text-base font-normal word-break-break-word dark:prose-invert",
        !chatMessage ? "text-muted-foreground" : "text-foreground",
        // Chat-optimized prose styling
        "prose-sm md:prose-base prose-pre:!m-0 prose-pre:!p-0",
        "prose-headings:font-semibold prose-headings:tracking-tight",
        "prose-p:leading-relaxed prose-p:mb-4",
        "prose-li:my-1 prose-ul:my-2 prose-ol:my-2",
        "prose-blockquote:border-l-primary/30 prose-blockquote:bg-muted/50 prose-blockquote:px-4 prose-blockquote:py-2 prose-blockquote:rounded-r-md"
      )}
    >
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeMathjax, rehypeRaw]}
        linkTarget="_blank"
        components={markdownComponents}
      >
        {processedChatMessage}
      </Markdown>
    </div>
  );
};
