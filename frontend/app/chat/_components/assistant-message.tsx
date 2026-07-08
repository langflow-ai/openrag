import { GitBranch } from "lucide-react";
import { motion } from "motion/react";
import dynamic from "next/dynamic";
import { useRef, useState } from "react";
import DogIcon from "@/components/icons/dog-icon";
import { preprocessCitations } from "@/components/markdown-citations";
import { ChunkPopup } from "./chunk-popup";
import { CitationCards } from "./citation-cards";

const MarkdownRenderer = dynamic(
  () =>
    import("@/components/markdown-renderer").then((m) => ({
      default: m.MarkdownRenderer,
    })),
  { ssr: false },
);

// Import the shared filename derivation helper
import { deriveDisplayFilename } from "@/components/markdown-citations";
import { Popover } from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
import { trackButton } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import type {
  FunctionCall,
  TokenUsage as TokenUsageType,
  ToolCallResult,
} from "../_types/types";
import { FunctionCallsContainer } from "./function-calls/container";
import { Message } from "./message";
import MessageActions from "./message-actions";
import { TokenUsage } from "./token-usage";

const EMPTY_FUNCTION_CALLS: FunctionCall[] = [];

const hasNestedResults = (
  value: unknown,
): value is [{ results: ToolCallResult[] }] => {
  if (!Array.isArray(value) || value.length !== 1) return false;
  const first = value[0];
  if (typeof first !== "object" || first === null || !("results" in first)) {
    return false;
  }
  return Array.isArray((first as { results?: unknown }).results);
};

const hideStreamingSourceMarkers = (text: string): string =>
  text
    .replace(/\s*(?:\[Source:\s*[^\]]*\]|\(Source:\s*[^)]*\))/gi, "")
    .replace(/\s*(?:\[Source:\s*[^\]]*|\(Source:\s*[^)]*)$/gi, "");

interface AssistantMessageProps {
  content: string;
  functionCalls?: FunctionCall[];
  messageIndex?: number;
  expandedFunctionCalls: Set<string>;
  onToggle: (functionCallId: string) => void;
  isStreaming?: boolean;
  showForkButton?: boolean;
  onFork?: (e: React.MouseEvent) => void;
  isCompleted?: boolean;
  isInactive?: boolean;
  animate?: boolean;
  delay?: number;
  isInitialGreeting?: boolean;
  usage?: TokenUsageType;
  timestamp?: Date;
  showFeedback?: boolean;
  interactiveCitations?: boolean;
  showFunctionCalls?: boolean;
  unstyledMessageContent?: boolean;
}

export function AssistantMessage({
  content,
  functionCalls = EMPTY_FUNCTION_CALLS,
  messageIndex,
  expandedFunctionCalls,
  onToggle,
  isStreaming = false,
  showForkButton = false,
  onFork,
  isCompleted = false,
  isInactive = false,
  animate = true,
  delay = 0.2,
  isInitialGreeting = false,
  usage,
  timestamp,
  showFeedback = true,
  interactiveCitations = true,
  showFunctionCalls = true,
  unstyledMessageContent = false,
}: AssistantMessageProps) {
  const [activeChunkIndex, setActiveChunkIndex] = useState<number | null>(null);
  const citationCardRefs = useRef<Map<number, HTMLElement> | null>(null);
  if (citationCardRefs.current === null) {
    citationCardRefs.current = new Map();
  }

  const openChunkPopover = (index: number, _anchorElement: HTMLElement) => {
    setActiveChunkIndex(index);
  };

  const openChunkPopoverFromText = (
    index: number,
    citationElement: HTMLElement,
  ) => {
    openChunkPopover(
      index,
      citationCardRefs.current?.get(index) ?? citationElement,
    );
  };

  const setCitationCardRef = (index: number, element: HTMLElement | null) => {
    if (element) {
      citationCardRefs.current?.set(index, element);
    } else {
      citationCardRefs.current?.delete(index);
    }
  };

  const closeChunkPopover = () => {
    setActiveChunkIndex(null);
  };

  const trackFeedback = (feedback: "like" | "dislike") => {
    trackButton({
      action: feedback,
      elementId: "message-feedback",
      namespace: "chat",
      CTA: feedback === "like" ? "Like Message" : "Dislike Message",
      timestamp: timestamp?.getTime(),
    });
  };

  // Extract all retrieved search results from function calls
  const retrievalSources: ToolCallResult[] = [];
  for (const call of functionCalls ?? EMPTY_FUNCTION_CALLS) {
    if (call.status !== "completed" || !call.result) continue;

    const items = hasNestedResults(call.result)
      ? call.result[0].results
      : call.result;
    if (Array.isArray(items)) {
      retrievalSources.push(...items);
    }
  }

  const renderContent = isStreaming
    ? hideStreamingSourceMarkers(content)
    : content;

  // Parse citations and preprocess content
  const { text: processedContent, citedSources } = preprocessCitations(
    renderContent,
    retrievalSources,
  );

  const displayMessageText = isStreaming
    ? processedContent.trim()
      ? processedContent +
        ' <span class="inline-block w-1 h-4 bg-primary ml-1 animate-pulse"></span>'
      : '<span class="text-muted-foreground italic">Thinking<span class="thinking-dots"></span></span>'
    : processedContent;

  const activeCitedSource = citedSources.find(
    (s) => s.index === activeChunkIndex,
  );

  return (
    <motion.div
      initial={animate ? { opacity: 0, y: -20 } : { opacity: 1, y: 0 }}
      animate={{ opacity: 1, y: 0 }}
      transition={
        animate
          ? { duration: 0.4, delay: delay, ease: "easeOut" }
          : { duration: 0 }
      }
      className={isCompleted ? "opacity-50" : ""}
    >
      <Popover
        open={activeChunkIndex !== null}
        onOpenChange={(open) => {
          if (!open) closeChunkPopover();
        }}
      >
        <Message
          isAssistant
          unstyledContent={unstyledMessageContent}
          icon={
            <div className="w-8 h-8 flex items-center justify-center flex-shrink-0 select-none">
              {/* Dog icon with bark animation when greeting */}
              <motion.div
                initial={isInitialGreeting ? { rotate: -5, y: -1 } : false}
                animate={
                  isInitialGreeting
                    ? {
                        rotate: [-5, -8, -5, 0],
                        y: [-1, -2, -1, 0],
                      }
                    : {}
                }
                transition={
                  isInitialGreeting
                    ? {
                        duration: 0.8,
                        times: [0, 0.4, 0.7, 1],
                        ease: "easeInOut",
                      }
                    : {}
                }
              >
                <DogIcon
                  className="h-6 w-6 transition-colors duration-300"
                  disabled={isCompleted || isInactive}
                />
              </motion.div>
            </div>
          }
          actions={
            showForkButton && onFork ? (
              <button
                type="button"
                onClick={onFork}
                className="opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-accent rounded text-muted-foreground hover:text-foreground"
                title="Fork conversation from here"
              >
                <GitBranch className="h-3 w-3" />
              </button>
            ) : undefined
          }
        >
          {showFunctionCalls && (
            <FunctionCallsContainer
              functionCalls={functionCalls}
              messageIndex={messageIndex}
              expandedFunctionCalls={expandedFunctionCalls}
              onToggle={onToggle}
              isStreaming={isStreaming}
            />
          )}
          <div className="relative">
            {/* Slide animation for initial greeting */}
            <motion.div
              initial={isInitialGreeting ? { opacity: 0, x: -16 } : false}
              animate={
                isInitialGreeting
                  ? {
                      opacity: [0, 0, 1, 1],
                      x: [-16, -8, 0, 0],
                    }
                  : {}
              }
              transition={
                isInitialGreeting
                  ? {
                      duration: 0.8,
                      times: [0, 0.3, 0.6, 1],
                      ease: "easeOut",
                    }
                  : {}
              }
            >
              <MarkdownRenderer
                className={cn(
                  "text-sm py-1.5 transition-colors duration-300",
                  isCompleted
                    ? "text-placeholder-foreground"
                    : "text-foreground",
                )}
                chatMessage={displayMessageText}
                onCitationClick={
                  interactiveCitations ? openChunkPopoverFromText : undefined
                }
              />

              {/* Citation Cards */}
              {!isStreaming && (
                <CitationCards
                  citedSources={citedSources}
                  activeCardIndex={activeChunkIndex}
                  onCardClick={
                    interactiveCitations ? openChunkPopover : undefined
                  }
                  onCardRef={
                    interactiveCitations ? setCitationCardRef : undefined
                  }
                  interactive={interactiveCitations}
                />
              )}

              {!isStreaming &&
                (usage || (!isInitialGreeting && showFeedback)) && (
                  <>
                    <Separator className="my-4 w-full bg-border" />
                    <div className="flex justify-end gap-4">
                      {usage && !isStreaming && <TokenUsage usage={usage} />}
                      {!isInitialGreeting && showFeedback && !isStreaming && (
                        <MessageActions trackFeedback={trackFeedback} />
                      )}
                    </div>
                  </>
                )}
            </motion.div>
          </div>
        </Message>

        {/* Chunk Details Popup Modal */}
        {interactiveCitations && activeCitedSource && (
          <ChunkPopup
            onClose={closeChunkPopover}
            chunkNumber={activeCitedSource.index}
            filename={deriveDisplayFilename(
              activeCitedSource.item.data?.file_path,
              activeCitedSource.item.filename,
              "Document",
            )}
            score={
              activeCitedSource.item.score !== undefined
                ? activeCitedSource.item.score
                : 0
            }
            sourceText={
              activeCitedSource.item.data?.text ||
              activeCitedSource.item.text ||
              ""
            }
            item={activeCitedSource.item}
          />
        )}
      </Popover>
    </motion.div>
  );
}
