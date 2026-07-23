import { defaultSchema } from "hast-util-sanitize";
import dynamic from "next/dynamic";
import Markdown from "react-markdown";
import rehypeMathjax from "rehype-mathjax";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

// VULN-13906: react-markdown's rehypeRaw lets raw HTML embedded in markdown text
// (e.g. from a retrieved document or an LLM echoing injected content) become real
// DOM nodes. rehypeSanitize strips anything not explicitly allowed here — scripts,
// event handler attributes, iframes, etc. — while still permitting the MathJax SVG
// output (mjx-container + inline svg) that rehypeMathjax renders.
const markdownSanitizeSchema = {
  ...defaultSchema,
  tagNames: [
    ...(defaultSchema.tagNames || []),
    "mjx-container",
    "svg",
    "g",
    "path",
    "use",
    "rect",
    "defs",
    "text",
    "tspan",
  ],
  attributes: {
    ...defaultSchema.attributes,
    "mjx-container": ["className", "jax", "display", "style"],
    svg: [
      "viewBox",
      "width",
      "height",
      "style",
      "xmlns",
      "focusable",
      "role",
      "ariaHidden",
    ],
    g: ["transform", "fill", "stroke", "strokeWidth", "dataMmlNode"],
    path: ["d", "transform", "fill", "stroke", "strokeWidth"],
    use: ["href", "xlinkHref", "x", "y", "width", "height", "transform"],
    rect: ["x", "y", "width", "height", "fill", "stroke"],
    text: ["x", "y", "transform", "fontSize"],
    tspan: ["x", "y"],
  },
};

// Only http(s)/mailto links are ever safe to render as clickable — everything
// else (javascript:, data:, vbscript:, etc.) is dropped rather than passed through.
const safeUrlTransform = (url: string): string => {
  try {
    const parsed = new URL(url, "http://resolve-relative.invalid");
    if (["http:", "https:", "mailto:"].includes(parsed.protocol)) {
      return url;
    }
  } catch {
    // Not a parseable absolute/relative URL (e.g. a bare "#citation-0" fragment) —
    // allow it through only if it's a same-page fragment link.
    if (url.startsWith("#")) {
      return url;
    }
  }
  return "";
};

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

const isMarkdownTable = (text: string): boolean => {
  if (!text?.trim()) return false;

  // Single regex to detect markdown table with header separator
  return /\|.*\|.*\n\s*\|[\s\-:]+\|/m.test(text);
};

const cleanupTableEmptyCells = (text: string): string => {
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
        rehypePlugins={[
          rehypeMathjax,
          rehypeRaw,
          [rehypeSanitize, markdownSanitizeSchema],
        ]}
        urlTransform={safeUrlTransform}
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
              if (!onCitationClick) {
                return (
                  <span className="inline-flex items-center justify-center px-0.5 text-mmd text-accent-purple-foreground select-none align-baseline">
                    {props.children}
                  </span>
                );
              }
              return (
                <button
                  type="button"
                  onClick={(event) =>
                    onCitationClick(index, event.currentTarget)
                  }
                  className="inline-flex items-center justify-center px-0.5 text-mmd text-accent-purple-foreground transition-all cursor-pointer select-none align-baseline"
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
