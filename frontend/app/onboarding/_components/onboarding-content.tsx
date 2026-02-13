"use client";

import { useEffect, useRef, useState } from "react";
import { StickToBottom } from "use-stick-to-bottom";
import { getFilterById } from "@/app/api/queries/useGetFilterByIdQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { useUpdateOnboardingStateMutation } from "@/app/api/mutations/useUpdateOnboardingStateMutation";
import { AssistantMessage } from "@/app/chat/_components/assistant-message";
import Nudges from "@/app/chat/_components/nudges";
import { UserMessage } from "@/app/chat/_components/user-message";
import type { Message, SelectedFilters } from "@/app/chat/_types/types";
import OnboardingCard from "@/app/onboarding/_components/onboarding-card";
import { useChat } from "@/contexts/chat-context";
import { useChatStreaming } from "@/hooks/useChatStreaming";

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
  const { data: settings } = useGetSettingsQuery();
  const updateOnboardingMutation = useUpdateOnboardingStateMutation();
  const parseFailedRef = useRef(false);
  const [responseId, setResponseId] = useState<string | null>(null);
  
  // Initialize from backend settings
  const [selectedNudge, setSelectedNudge] = useState<string>(() => {
    return settings?.onboarding?.selected_nudge || "";
  });
  
  const [assistantMessage, setAssistantMessage] = useState<Message | null>(
    () => {
      // Get from backend settings
      if (settings?.onboarding?.assistant_message) {
        const msg = settings.onboarding.assistant_message;
        return {
          role: msg.role as "user" | "assistant",
          content: msg.content,
          timestamp: new Date(msg.timestamp),
        };
      }
      return null;
    },
  );

  // Sync state when settings change
  useEffect(() => {
    if (settings?.onboarding?.selected_nudge) {
      setSelectedNudge(settings.onboarding.selected_nudge);
    }
    if (settings?.onboarding?.assistant_message) {
      const msg = settings.onboarding.assistant_message;
      setAssistantMessage({
        role: msg.role as "user" | "assistant",
        content: msg.content,
        timestamp: new Date(msg.timestamp),
      });
    }
  }, [settings?.onboarding]);

  // Handle parse errors by going back a step
  useEffect(() => {
    if (parseFailedRef.current && currentStep >= 2) {
      handleStepBack();
    }
  }, [handleStepBack, currentStep]);

  const { streamingMessage, isLoading, sendMessage } = useChatStreaming({
    onComplete: async (message, newResponseId) => {
      setAssistantMessage(message);
      // Save assistant message to backend
      await updateOnboardingMutation.mutateAsync({
        assistant_message: {
          role: message.role,
          content: message.content,
          timestamp: message.timestamp.toISOString(),
        },
      });
      
      if (newResponseId) {
        setResponseId(newResponseId);

        // Set the current conversation ID
        setCurrentConversationId(newResponseId);

        // Get filter ID from backend settings
        const openragDocsFilterId = settings?.onboarding?.openrag_docs_filter_id;
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
    setAssistantMessage(null);
    
    // Save selected nudge to backend and clear assistant message
    await updateOnboardingMutation.mutateAsync({
      selected_nudge: nudge,
      assistant_message: null,
    });
    
    setTimeout(async () => {
      // Check if we have the OpenRAG docs filter ID (sample data was ingested)
      const openragDocsFilterId = settings?.onboarding?.openrag_docs_filter_id;

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
      className="flex h-full flex-1 flex-col [&>div]:scrollbar-hide"
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
