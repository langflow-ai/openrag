import { GitBranch } from "lucide-react";
import { motion } from "motion/react";
import DogIcon from "@/components/icons/dog-icon";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { cn } from "@/lib/utils";
import type { FunctionCall, TokenUsage as TokenUsageType } from "../_types/types";
import { FunctionCalls } from "./function-calls";
import { Message } from "./message";
import { TokenUsage } from "./token-usage";

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
}

export function AssistantMessage({
  content,
  functionCalls = [],
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
}: AssistantMessageProps) {
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
      <Message
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
        <FunctionCalls
          functionCalls={functionCalls}
          messageIndex={messageIndex}
          expandedFunctionCalls={expandedFunctionCalls}
          onToggle={onToggle}
        />
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
                isCompleted ? "text-placeholder-foreground" : "text-foreground",
              )}
              chatMessage={
                isStreaming
                  ? content.trim()
                    ? content +
                      ' <span class="inline-block w-1 h-4 bg-primary ml-1 animate-pulse"></span>'
                    : '<span class="text-muted-foreground italic">Thinking<span class="thinking-dots"></span></span>'
                  : content
              }
            />
            {usage && !isStreaming && <TokenUsage usage={usage} />}
          </motion.div>
        </div>
      </Message>
    </motion.div>
  );
}
