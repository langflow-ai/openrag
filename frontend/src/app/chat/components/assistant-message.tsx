import { GitBranch } from "lucide-react";
import { motion } from "motion/react";
import DogIcon from "@/components/logo/dog-icon";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { cn } from "@/lib/utils";
import type { FunctionCall } from "../types";
import { FunctionCalls } from "./function-calls";
import { Message } from "./message";

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
            <DogIcon
              className="h-6 w-6 transition-colors duration-300"
              disabled={isCompleted || isInactive}
            />
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
          <MarkdownRenderer
            className={cn(
              "text-sm py-1.5 transition-colors duration-300",
              isCompleted ? "text-placeholder-foreground" : "text-foreground",
            )}
            chatMessage={
              isStreaming
                ? content +
                  ' <span class="inline-block w-1 h-4 bg-primary ml-1 animate-pulse"></span>'
                : content
            }
          />
        </div>
      </Message>
    </motion.div>
  );
}
