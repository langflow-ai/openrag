"use client";

import { useState } from "react";
import { AssistantMessage } from "@/app/chat/components/assistant-message";
import { UserMessage } from "@/app/chat/components/user-message";
import Nudges from "@/app/chat/nudges";
import type { Message } from "@/app/chat/types";
import OnboardingCard from "@/app/onboarding/components/onboarding-card";
import { useChatStreaming } from "@/hooks/useChatStreaming";
import { OnboardingStep } from "./onboarding-step";

export function OnboardingContent({
	handleStepComplete,
	currentStep,
}: {
	handleStepComplete: () => void;
	currentStep: number;
}) {
	const [responseId, setResponseId] = useState<string | null>(null);
	const [selectedNudge, setSelectedNudge] = useState<string>("");
	const [assistantMessage, setAssistantMessage] = useState<Message | null>(
		null,
	);

	const { streamingMessage, isLoading, sendMessage } = useChatStreaming({
		onComplete: (message, newResponseId) => {
			setAssistantMessage(message);
			if (newResponseId) {
				setResponseId(newResponseId);
			}
		},
		onError: (error) => {
			console.error("Chat error:", error);
			setAssistantMessage({
				role: "assistant",
				content:
					"Sorry, I couldn't connect to the chat service. Please try again.",
				timestamp: new Date(),
			});
		},
	});

	const NUDGES = ["What is OpenRAG?"];

	const handleNudgeClick = async (nudge: string) => {
		setSelectedNudge(nudge);
		setAssistantMessage(null);
		await sendMessage({
			prompt: nudge,
			previousResponseId: responseId || undefined,
		});
	};

	// Determine which message to show (streaming takes precedence)
	const displayMessage = streamingMessage || assistantMessage;

	return (
		<div className="space-y-6">
			<OnboardingStep
				isVisible={currentStep >= 0}
				isCompleted={currentStep > 0}
				text="Let's get started by setting up your model provider."
			>
				<OnboardingCard onComplete={handleStepComplete} />
			</OnboardingStep>

			<OnboardingStep
				isVisible={currentStep >= 1}
				isCompleted={currentStep > 1 || !!selectedNudge}
				text="Excellent, let's move on to learning the basics."
			>
				<div className="py-2">
					<Nudges
						onboarding
						nudges={NUDGES}
						handleSuggestionClick={handleNudgeClick}
					/>
				</div>
			</OnboardingStep>

			{/* User message - show when nudge is selected */}
			{currentStep >= 1 && !!selectedNudge && (
				<div className={currentStep > 1 ? "opacity-50" : ""}>
					<UserMessage content={selectedNudge} />
				</div>
			)}

			{/* Assistant message - show streaming or final message */}
			{currentStep >= 1 && !!selectedNudge && (displayMessage || isLoading) && (
				<div className={currentStep > 1 ? "opacity-50" : ""}>
					<AssistantMessage
						content={displayMessage?.content || ""}
						functionCalls={displayMessage?.functionCalls}
						messageIndex={0}
						expandedFunctionCalls={new Set()}
						onToggle={() => {}}
						isStreaming={!!streamingMessage}
					/>
					{!isLoading && displayMessage && currentStep === 1 && (
						<div className="mt-4">
							<button
								type="button"
								onClick={handleStepComplete}
								className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
							>
								Continue
							</button>
						</div>
					)}
				</div>
			)}

			<OnboardingStep
				isVisible={currentStep >= 2}
				isCompleted={currentStep > 2}
				text="Step 2: Connect your model"
			>
				<div className="space-y-4">
					<p className="text-muted-foreground">
						Choose and connect your preferred AI model provider.
					</p>
					<button
						type="button"
						onClick={handleStepComplete}
						className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
					>
						Continue
					</button>
				</div>
			</OnboardingStep>

			<OnboardingStep
				isVisible={currentStep >= 3}
				isCompleted={currentStep > 3}
				text="Step 3: You're all set!"
			>
				<div className="space-y-4">
					<p className="text-muted-foreground">
						Your account is ready to use. Let's start chatting!
					</p>
					<button
						type="button"
						onClick={handleStepComplete}
						className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
					>
						Go to Chat
					</button>
				</div>
			</OnboardingStep>
		</div>
	);
}
