"use client";

import { Loader2, User } from "lucide-react";
import { useState } from "react";
import Nudges from "@/app/chat/nudges";
import OnboardingCard from "@/app/onboarding/components/onboarding-card";
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
	const [assistantResponse, setAssistantResponse] = useState<string>("");
	const [isLoadingResponse, setIsLoadingResponse] = useState<boolean>(false);

	const NUDGES = ["What is OpenRAG?"];

	const handleNudgeClick = async (nudge: string) => {
		setSelectedNudge(nudge);
		setIsLoadingResponse(true);

		try {
			const requestBody: {
				prompt: string;
				stream?: boolean;
				previous_response_id?: string;
			} = {
				prompt: nudge,
				stream: false,
			};

			if (responseId) {
				requestBody.previous_response_id = responseId;
			}

			const response = await fetch("/api/chat", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
				},
				body: JSON.stringify(requestBody),
			});

			const result = await response.json();

			if (response.ok) {
				setAssistantResponse(result.response);
				if (result.response_id) {
					setResponseId(result.response_id);
				}
			} else {
				setAssistantResponse(
					"Sorry, I encountered an error. Please try again.",
				);
			}
		} catch (error) {
			console.error("Chat error:", error);
			setAssistantResponse(
				"Sorry, I couldn't connect to the chat service. Please try again.",
			);
		} finally {
			setIsLoadingResponse(false);
		}
	};

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
				text="Excellent, let’s move on to learning the basics."
			>
				<div className="py-2">
					<Nudges onboarding nudges={NUDGES} handleSuggestionClick={handleNudgeClick} />
				</div>
			</OnboardingStep>

			<OnboardingStep
				isVisible={currentStep >= 1 && !!selectedNudge}
				isCompleted={currentStep > 1}
				text={selectedNudge}
				icon={
					<div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0 select-none">
						<User className="h-4 w-4 text-primary" />
					</div>
				}
			>
			</OnboardingStep>

			<OnboardingStep
				isVisible={currentStep >= 1 && !!selectedNudge}
				isCompleted={currentStep > 1}
				text={isLoadingResponse ? "Thinking..." : assistantResponse}
				isMarkdown={!isLoadingResponse && !!assistantResponse}
			>
				{isLoadingResponse ? (
					<div className="flex items-center gap-2">
						<Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
					</div>
				) : (
					<button
						onClick={handleStepComplete}
						className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
					>
						Continue
					</button>
				)}
			</OnboardingStep>

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
