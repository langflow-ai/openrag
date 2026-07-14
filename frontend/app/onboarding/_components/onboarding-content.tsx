"use client";

import { useEffect, useRef, useState } from "react";
import { StickToBottom } from "use-stick-to-bottom";
import { useUpdateOnboardingStateMutation } from "@/app/api/mutations/useUpdateOnboardingStateMutation";
import { getFilterById } from "@/app/api/queries/useGetFilterByIdQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { AssistantMessage } from "@/app/chat/_components/assistant-message";
import Nudges from "@/app/chat/_components/nudges";
import { UserMessage } from "@/app/chat/_components/user-message";
import type {
  FunctionCall,
  Message,
  ToolCallResult,
} from "@/app/chat/_types/types";
import OnboardingCard from "@/app/onboarding/_components/onboarding-card";
import { useChat } from "@/contexts/chat-context";
import { useChatStreaming } from "@/hooks/useChatStreaming";
import { trackButton, trackLLMCall } from "@/lib/analytics";
import type { FilterInput } from "@/lib/filter-normalization";
import { buildSearchPayloadFilters } from "@/lib/filter-normalization";

import { OnboardingStep } from "./onboarding-step";
import OnboardingUpload from "./onboarding-upload";

// Filters for OpenRAG documentation
const OPENRAG_DOCS_FILTERS: FilterInput = {
  data_sources: [],
  document_types: [],
  owners: [],
  connector_types: ["openrag_docs"],
};

const sanitizeCitationResult = (item: ToolCallResult): ToolCallResult => {
  const data = (() => {
    if (!item.data) return undefined;

    const sanitizedData = {
      file_path: item.data.file_path,
      page: item.data.page,
      score: item.data.score,
    };

    return Object.values(sanitizedData).some((value) => value !== undefined)
      ? sanitizedData
      : undefined;
  })();

  return {
    data,
    chunk_id: item.chunk_id,
    id: item.id,
    filename: item.filename,
    page: item.page ?? item.data?.page,
    score: item.score ?? item.data?.score,
  };
};

const hasNestedResults = (
  value: unknown,
): value is [{ results: ToolCallResult[] }] => {
  if (!Array.isArray(value) || value.length !== 1) return false;
  const first = value[0];
  if (typeof first !== "object" || first === null || !("results" in first)) {
    return false;
  }
  return Array.isArray((first as { results?: unknown }).results);
};

const sanitizeOnboardingFunctionCalls = (
  functionCalls: FunctionCall[] | undefined,
): FunctionCall[] | undefined => {
  if (!functionCalls || functionCalls.length === 0) return undefined;

  return functionCalls.map(({ name, status, result }) => {
    const sanitizedResult = hasNestedResults(result)
      ? [{ results: result[0].results.map(sanitizeCitationResult) }]
      : Array.isArray(result)
        ? result.map(sanitizeCitationResult)
        : undefined;

    return {
      name,
      status,
      result: sanitizedResult,
    };
  });
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
          functionCalls: msg.functionCalls || undefined,
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
        functionCalls: msg.functionCalls || undefined,
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
      trackLLMCall({
        mode: "onboarding",
        model: settings?.agent?.llm_model,
        inputTokens: message.usage?.input_tokens,
        outputTokens: message.usage?.output_tokens,
      });
      setAssistantMessage(message);
      // Save assistant message to backend
      await updateOnboardingMutation.mutateAsync({
        assistant_message: {
          role: message.role,
          content: message.content,
          timestamp: message.timestamp.toISOString(),
          functionCalls: sanitizeOnboardingFunctionCalls(message.functionCalls),
        },
      });

      if (newResponseId) {
        setResponseId(newResponseId);

        // Set the current conversation ID
        setCurrentConversationId(newResponseId);

        // Get filter ID from backend settings
        const openragDocsFilterId =
          settings?.onboarding?.openrag_docs_filter_id;
        if (openragDocsFilterId) {
          try {
            // Load the filter and set it in the context with explicit responseId
            // This ensures the filter is saved to localStorage with the correct conversation ID
            const filter = await getFilterById(openragDocsFilterId);
            if (filter) {
              // Pass explicit newResponseId to ensure correct localStorage association
              setConversationFilter(filter, newResponseId);
            }
          } catch (error) {
            console.error(
              "Failed to associate filter with conversation:",
              error,
            );
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
    trackButton({
      CTA: `Learn Basics - ${nudge}`,
      elementId: "onboarding-nudge",
      namespace: "onboarding",
    });
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
      if (openragDocsFilterId) {
        try {
          const filter = await getFilterById(openragDocsFilterId);
          if (filter) {
            // Pass null to skip localStorage save - no conversation exists yet
            setConversationFilter(filter, null);
            filterToUse = filter;
          }
        } catch (error) {
          console.error("Failed to load OpenRAG docs filter:", error);
        }
      }
      await sendMessage({
        prompt: nudge,
        previousResponseId: responseId || undefined,
        // Send both filter_id and filters (selections)
        filter_id: filterToUse?.id,
        filters: openragDocsFilterId
          ? buildSearchPayloadFilters(OPENRAG_DOCS_FILTERS)
          : undefined,
      });
    }, 1500);
  };

  // Determine which message to show (streaming takes precedence)
  const displayMessage = streamingMessage || assistantMessage;

  useEffect(() => {
    if (currentStep === 2 && !isLoading && displayMessage) {
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
        <div
          className="flex flex-col place-self-center w-full space-y-6"
          data-testid="onboarding-content"
        >
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
                showFeedback={false}
                interactiveCitations={false}
                showFunctionCalls={false}
                unstyledMessageContent
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
