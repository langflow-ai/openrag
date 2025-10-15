import { Bot, GitBranch } from "lucide-react";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { FunctionCalls } from "./function-calls";
import { Message } from "./message";
import type { FunctionCall } from "../types";
import DogIcon from "@/components/logo/dog-icon";

interface AssistantMessageProps {
  content: string;
  functionCalls?: FunctionCall[];
  messageIndex?: number;
  expandedFunctionCalls: Set<string>;
  onToggle: (functionCallId: string) => void;
  isStreaming?: boolean;
  showForkButton?: boolean;
  onFork?: (e: React.MouseEvent) => void;
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
}: AssistantMessageProps) {
  const updatedOnboarding = process.env.UPDATED_ONBOARDING === "true";
  const IconComponent = updatedOnboarding ? DogIcon : Bot;

  return (
    <Message
      icon={
        <div className="w-8 h-8 rounded-lg bg-accent/20 flex items-center justify-center flex-shrink-0 select-none">
          <IconComponent className="h-4 w-4 text-accent-foreground" />
        </div>
      }
      actions={
        showForkButton && onFork ? (
          <button
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
      <MarkdownRenderer chatMessage={content} />
      {isStreaming && (
        <span className="inline-block w-2 h-4 bg-blue-400 ml-1 animate-pulse"></span>
      )}
    </Message>
  );
}
