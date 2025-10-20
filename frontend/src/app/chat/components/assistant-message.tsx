import { GitBranch } from "lucide-react";
import DogIcon from "@/components/logo/dog-icon";
import { MarkdownRenderer } from "@/components/markdown-renderer";
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
	return (
		<Message
			icon={
				<div className="w-8 h-8 rounded-lg bg-accent/20 flex items-center justify-center flex-shrink-0 select-none">
					<DogIcon className="h-6 w-6 text-accent-foreground" />
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
			<div className="relative">
				<MarkdownRenderer
					className="text-foreground text-sm py-1.5"
					chatMessage={
						isStreaming
							? content +
								' <span class="inline-block w-1 h-4 bg-primary ml-1 animate-pulse"></span>'
							: content
					}
				/>
			</div>
		</Message>
	);
}
