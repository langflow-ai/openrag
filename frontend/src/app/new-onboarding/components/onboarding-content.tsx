"use client";

import { useEffect, useState } from "react";
import { StickToBottom } from "use-stick-to-bottom";
import { AssistantMessage } from "@/app/chat/components/assistant-message";
import { UserMessage } from "@/app/chat/components/user-message";
import Nudges from "@/app/chat/nudges";
import type { Message } from "@/app/chat/types";
import OnboardingCard from "@/app/onboarding/components/onboarding-card";
import { useChatStreaming } from "@/hooks/useChatStreaming";

import { OnboardingStep } from "./onboarding-step";
import OnboardingUpload from "./onboarding-upload";

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
		setTimeout(async () => {
			await sendMessage({
				prompt: nudge,
				previousResponseId: responseId || undefined,
			});
		}, 1500);
	};

	// Determine which message to show (streaming takes precedence)
	const displayMessage = streamingMessage || assistantMessage;

	useEffect(() => {
		if (currentStep === 1 && !isLoading && !!displayMessage) {
			handleStepComplete();
		}
	}, [isLoading, displayMessage, handleStepComplete]);

	return (
		<StickToBottom
			className="flex h-full flex-1 flex-col"
			resize="smooth"
			initial="instant"
			mass={1}
		>
			<StickToBottom.Content className="flex flex-col min-h-full overflow-x-hidden px-8 py-6">
				<div className="flex flex-col place-self-center w-full space-y-6">
					{/* Step 1 */}
					<OnboardingStep
						isVisible={currentStep >= 0}
						isCompleted={currentStep > 0}
						text="Let's get started by setting up your model provider."
					>
						<OnboardingCard onComplete={handleStepComplete} />
					</OnboardingStep>

					{/* Step 2 */}
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
						<UserMessage
							content={selectedNudge}
							isCompleted={currentStep > 2}
						/>
					)}

					{/* Assistant message - show streaming or final message */}
					{currentStep >= 1 &&
						!!selectedNudge &&
						(displayMessage || isLoading) && (
							<AssistantMessage
								content={displayMessage?.content || ""}
								functionCalls={displayMessage?.functionCalls}
								messageIndex={0}
								expandedFunctionCalls={new Set()}
								onToggle={() => {}}
								isStreaming={!!streamingMessage}
								isCompleted={currentStep > 2}
							/>
						)}
					
					{/* Step 3 */}
					<OnboardingStep
						isVisible={currentStep >= 2 && !isLoading && !!displayMessage}
						isCompleted={currentStep > 2}
						text="Now, let's add your data."
						hideIcon={true}
					>
						<OnboardingUpload onComplete={handleStepComplete} />
					</OnboardingStep>

					{/* Step 4 */}
					<OnboardingStep
						isVisible={currentStep >= 3}
						isCompleted={currentStep > 3}
						text="Step 3: You're all set!"
					>
						<div className="space-y-4">
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
			</StickToBottom.Content>
		</StickToBottom>
	);
}
