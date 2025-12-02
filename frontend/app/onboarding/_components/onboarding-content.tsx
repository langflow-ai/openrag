"use client";

import { useEffect, useRef, useState } from "react";
import { StickToBottom } from "use-stick-to-bottom";
import { getFilterById } from "@/app/api/queries/useGetFilterByIdQuery";
import { AssistantMessage } from "@/app/chat/_components/assistant-message";
import Nudges from "@/app/chat/_components/nudges";
import { UserMessage } from "@/app/chat/_components/user-message";
import type { Message, SelectedFilters } from "@/app/chat/_types/types";
import OnboardingCard from "@/app/onboarding/_components/onboarding-card";
import { useChat } from "@/contexts/chat-context";
import { useChatStreaming } from "@/hooks/useChatStreaming";
import {
  ONBOARDING_ASSISTANT_MESSAGE_KEY,
  ONBOARDING_OPENRAG_DOCS_FILTER_ID_KEY,
  ONBOARDING_SELECTED_NUDGE_KEY,
} from "@/lib/constants";

import { OnboardingStep } from "./onboarding-step";
import OnboardingUpload from "./onboarding-upload";

// Filters for OpenRAG documentation
const OPENRAG_DOCS_FILTERS: SelectedFilters = {
  data_sources: ["openrag-documentation.pdf"],
  document_types: [],
  owners: [],
};

export function OnboardingContent({
  handleStepComplete,
  handleStepBack,
  currentStep,
}: {
  handleStepComplete: () => void;
  handleStepBack: () => void;
  currentStep: number;
}) {
  const { setConversationFilter, setCurrentConversationId } = useChat();
  const parseFailedRef = useRef(false);
  const [responseId, setResponseId] = useState<string | null>(null);
  const [selectedNudge, setSelectedNudge] = useState<string>(() => {
    // Retrieve selected nudge from localStorage on mount
    if (typeof window === "undefined") return "";
    return localStorage.getItem(ONBOARDING_SELECTED_NUDGE_KEY) || "";
  });
  const [assistantMessage, setAssistantMessage] = useState<Message | null>(
    () => {
      // Retrieve assistant message from localStorage on mount
      if (typeof window === "undefined") return null;
      const savedMessage = localStorage.getItem(
        ONBOARDING_ASSISTANT_MESSAGE_KEY,
      );
      if (savedMessage) {
        try {
          const parsed = JSON.parse(savedMessage);
          // Convert timestamp string back to Date object
          return {
            ...parsed,
            timestamp: new Date(parsed.timestamp),
          };
        } catch (error) {
          console.error("Failed to parse saved assistant message:", error);
          parseFailedRef.current = true;
          // Clear corrupted data - will go back a step in useEffect
          if (typeof window !== "undefined") {
            localStorage.removeItem(ONBOARDING_ASSISTANT_MESSAGE_KEY);
            localStorage.removeItem(ONBOARDING_SELECTED_NUDGE_KEY);
          }
          return null;
        }
      }
      return null;
    },
  );

  // Handle parse errors by going back a step
  useEffect(() => {
    if (parseFailedRef.current && currentStep >= 2) {
      handleStepBack();
    }
  }, [handleStepBack, currentStep]);

  const { streamingMessage, isLoading, sendMessage } = useChatStreaming({
    onComplete: async (message, newResponseId) => {
      setAssistantMessage(message);
      // Save assistant message to localStorage when complete
      if (typeof window !== "undefined") {
        try {
          localStorage.setItem(
            ONBOARDING_ASSISTANT_MESSAGE_KEY,
            JSON.stringify(message),
          );
        } catch (error) {
          console.error(
            "Failed to save assistant message to localStorage:",
            error,
          );
        }
      }
      if (newResponseId) {
        setResponseId(newResponseId);

        // Set the current conversation ID
        setCurrentConversationId(newResponseId);

        // Save the filter association for this conversation
        const openragDocsFilterId = localStorage.getItem(ONBOARDING_OPENRAG_DOCS_FILTER_ID_KEY);
        if (openragDocsFilterId) {
          try {
            // Load the filter and set it in the context with explicit responseId
            // This ensures the filter is saved to localStorage with the correct conversation ID
            const filter = await getFilterById(openragDocsFilterId);
            if (filter) {
              // Pass explicit newResponseId to ensure correct localStorage association
              setConversationFilter(filter, newResponseId);
              console.log("[ONBOARDING] Saved filter association:", `conversation_filter_${newResponseId}`, "=", openragDocsFilterId);
            }
          } catch (error) {
            console.error("Failed to associate filter with conversation:", error);
          }
        }
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
    // Save selected nudge to localStorage
    if (typeof window !== "undefined") {
      localStorage.setItem(ONBOARDING_SELECTED_NUDGE_KEY, nudge);
    }
    setAssistantMessage(null);
    // Clear saved assistant message when starting a new conversation
    if (typeof window !== "undefined") {
      localStorage.removeItem(ONBOARDING_ASSISTANT_MESSAGE_KEY);
    }
    setTimeout(async () => {
      // Check if we have the OpenRAG docs filter ID (sample data was ingested)
      const openragDocsFilterId =
        typeof window !== "undefined"
          ? localStorage.getItem(ONBOARDING_OPENRAG_DOCS_FILTER_ID_KEY)
          : null;

      // Load and set the OpenRAG docs filter if available
      let filterToUse = null;
      console.log("[ONBOARDING] openragDocsFilterId:", openragDocsFilterId);
      if (openragDocsFilterId) {
        try {
          const filter = await getFilterById(openragDocsFilterId);
          console.log("[ONBOARDING] Loaded filter:", filter);
          if (filter) {
            // Pass null to skip localStorage save - no conversation exists yet
            setConversationFilter(filter, null);
            filterToUse = filter;
          }
        } catch (error) {
          console.error("Failed to load OpenRAG docs filter:", error);
        }
      }

      console.log("[ONBOARDING] Sending message with filter_id:", filterToUse?.id);
      await sendMessage({
        prompt: nudge,
        previousResponseId: responseId || undefined,
        // Send both filter_id and filters (selections)
        filter_id: filterToUse?.id,
        filters: openragDocsFilterId ? OPENRAG_DOCS_FILTERS : undefined,
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

          {/* Step 3 */}
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

          {/* Step 4 */}
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
