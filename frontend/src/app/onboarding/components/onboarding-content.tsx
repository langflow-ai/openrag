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
    if (currentStep === 2 && !isLoading && !!displayMessage) {
      handleStepComplete();
    }
  }, [isLoading, displayMessage, handleStepComplete, currentStep]);

  return (
    <StickToBottom
      className="flex h-full flex-1 flex-col"
      resize="smooth"
      initial="instant"
      mass={1}
    >
      <StickToBottom.Content className="flex flex-col min-h-full overflow-x-hidden px-8 py-6">
        <div className="flex flex-col place-self-center w-full space-y-6">
          {/* Step 1 - LLM Provider */}
          <OnboardingStep
            isVisible={currentStep >= 0}
            isCompleted={currentStep > 0}
            showCompleted={true}
            text="Let's get started by setting up your LLM provider."
          >
            <OnboardingCard
              onComplete={() => {
                handleStepComplete();
              }}
              isCompleted={currentStep > 0}
            />
          </OnboardingStep>

          {/* Step 2 - Embedding provider and ingestion */}
          <OnboardingStep
            isVisible={currentStep >= 1}
            isCompleted={currentStep > 1}
            showCompleted={true}
            text="Now, let's set up your embedding provider."
          >
            <OnboardingCard
              isEmbedding={true}
              onComplete={() => {
                handleStepComplete();
              }}
              isCompleted={currentStep > 1}
            />
          </OnboardingStep>

          {/* Step 2 */}
          <OnboardingStep
            isVisible={currentStep >= 2}
            isCompleted={currentStep > 2 || !!selectedNudge}
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
          {currentStep >= 2 && !!selectedNudge && (
            <UserMessage
              content={selectedNudge}
              isCompleted={currentStep > 3}
            />
          )}

          {/* Assistant message - show streaming or final message */}
          {currentStep >= 2 &&
            !!selectedNudge &&
            (displayMessage || isLoading) && (
              <AssistantMessage
                content={displayMessage?.content || ""}
                functionCalls={displayMessage?.functionCalls}
                messageIndex={0}
                expandedFunctionCalls={new Set()}
                onToggle={() => {}}
                isStreaming={!!streamingMessage}
                isCompleted={currentStep > 3}
              />
            )}

          {/* Step 3 */}
          <OnboardingStep
            isVisible={currentStep >= 3 && !isLoading && !!displayMessage}
            isCompleted={currentStep > 3}
            text="Lastly, let's add your data."
            hideIcon={true}
          >
            <OnboardingUpload onComplete={handleStepComplete} />
          </OnboardingStep>
        </div>
      </StickToBottom.Content>
    </StickToBottom>
  );
}
