"use client";

import { useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  type ChatConversation,
  useGetConversationsQuery,
} from "@/app/api/queries/useGetConversationsQuery";
import { getFilterById } from "@/app/api/queries/useGetFilterByIdQuery";
import type { Settings } from "@/app/api/queries/useGetSettingsQuery";
import { useUpdateOnboardingStateMutation } from "@/app/api/mutations/useUpdateOnboardingStateMutation";
import { OnboardingContent } from "@/app/onboarding/_components/onboarding-content";
import { ProgressBar } from "@/app/onboarding/_components/progress-bar";
import { AnimatedConditional } from "@/components/animated-conditional";
import { Header } from "@/components/header";
import { Navigation } from "@/components/navigation";
import { useAuth } from "@/contexts/auth-context";
import { useChat } from "@/contexts/chat-context";
import {
  ANIMATION_DURATION,
  HEADER_HEIGHT,
  SIDEBAR_WIDTH,
  TOTAL_ONBOARDING_STEPS,
} from "@/lib/constants";
import { cn } from "@/lib/utils";

export function ChatRenderer({
  settings,
  children,
}: {
  settings: Settings | undefined;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient(); // Move hook to component level
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const {
    endpoint,
    refreshTrigger,
    refreshConversations,
    startNewConversation,
    setConversationFilter,
    setOnboardingComplete,
  } = useChat();

  // Initialize onboarding state from backend settings
  const [currentStep, setCurrentStep] = useState<number>(() => {
    return settings?.onboarding?.current_step ?? 0;
  });

  const [showLayout, setShowLayout] = useState<boolean>(() => {
    // Show layout only if onboarding is complete (current_step >= TOTAL_ONBOARDING_STEPS)
    // This means onboarding will show even if edited=true, as long as it's not complete
    const onboardingStep = settings?.onboarding?.current_step ?? 0;
    return onboardingStep >= TOTAL_ONBOARDING_STEPS;
  });

  // Update currentStep and showLayout when settings change
  useEffect(() => {
    if (settings?.onboarding?.current_step !== undefined) {
      setCurrentStep(settings.onboarding.current_step);
      // Update showLayout based on whether onboarding is complete
      setShowLayout(settings.onboarding.current_step >= TOTAL_ONBOARDING_STEPS);
    }
  }, [settings?.onboarding?.current_step]);

  // Only fetch conversations on chat page
  const isOnChatPage = pathname === "/" || pathname === "/chat";
  const { data: conversations = [], isLoading: isConversationsLoading } =
    useGetConversationsQuery(endpoint, refreshTrigger, {
      enabled: isOnChatPage && (isAuthenticated || isNoAuthMode),
    }) as { data: ChatConversation[]; isLoading: boolean };

  const handleNewConversation = () => {
    refreshConversations();
    startNewConversation();
  };

  // Navigate to /chat when onboarding is active so animation reveals chat underneath
  useEffect(() => {
    if (!showLayout && pathname !== "/chat" && pathname !== "/") {
      router.push("/chat");
    }
  }, [showLayout, pathname, router]);

  // Helper to store default filter ID for new conversations after onboarding
  const storeDefaultFilterForNewConversations = useCallback(
    async (preferUserDoc: boolean, settingsToUse?: Settings) => {
      // Use provided settings or fall back to prop
      const currentSettings = settingsToUse || settings;
      
      if (typeof window === "undefined") {
        return;
      }

      // Check if we already have a default filter set
      const existingDefault = localStorage.getItem("default_conversation_filter_id");
      
      if (existingDefault) {
        // Try to apply it to context state (don't save to localStorage to avoid overwriting)
        try {
          const filter = await getFilterById(existingDefault);
          if (filter) {
            // Pass null to skip localStorage save
            setConversationFilter(filter, null);
            return; // Successfully loaded and set, we're done
          }
        } catch (error) {
          console.error("Failed to load existing default filter, will set new one:", error);
          // Filter doesn't exist anymore, clear it and continue to set a new one
          localStorage.removeItem("default_conversation_filter_id");
        }
      }

      // Try to get the appropriate filter ID from settings
      let filterId: string | null = null;

      if (preferUserDoc) {
        // Completed full onboarding - prefer user document filter
        filterId = currentSettings?.onboarding?.user_doc_filter_id || null;
      }

      // Fall back to OpenRAG docs filter
      if (!filterId) {
        filterId = currentSettings?.onboarding?.openrag_docs_filter_id || null;
      }


      if (filterId) {
        // Store this as the default filter for new conversations
        localStorage.setItem("default_conversation_filter_id", filterId);

        // Apply filter to context state only (don't save to localStorage since there's no conversation yet)
        // The default_conversation_filter_id will be used when a new conversation is started
        try {
          const filter = await getFilterById(filterId);
          if (filter) {
            // Pass null to skip localStorage save - this prevents overwriting existing conversation filters
            setConversationFilter(filter, null);
          }
        } catch (error) {
          console.error("[FILTER] Failed to set onboarding filter:", error);
        }
      }
    },
    [setConversationFilter, settings?.onboarding?.user_doc_filter_id, settings?.onboarding?.openrag_docs_filter_id]
  );

  // Note: Current step is now saved to backend via handleStepComplete
  // No need to save on every change, only on completion

  const updateOnboardingMutation = useUpdateOnboardingStateMutation();

  const handleStepComplete = async () => {
    if (currentStep < TOTAL_ONBOARDING_STEPS - 1) {
      const nextStep = currentStep + 1;
      setCurrentStep(nextStep);
      // Save step to backend
      await updateOnboardingMutation.mutateAsync({ current_step: nextStep });
    } else {

      // IMPORTANT: Refetch settings to get the latest filter IDs that were saved during onboarding
      // The filter IDs are saved asynchronously by mutations, so we need fresh data
      await queryClient.refetchQueries({ queryKey: ["settings"] });
      
      // Get the fresh settings after refetch
      const freshSettings = queryClient.getQueryData(["settings"]) as Settings | undefined;

      // Store the user document filter as default for new conversations
      // Pass fresh settings to ensure we have the latest filter IDs
      await storeDefaultFilterForNewConversations(true, freshSettings);

      // Onboarding is complete - set step to TOTAL_ONBOARDING_STEPS to indicate completion
      // and clear intermediate state in backend (but keep filter IDs for reference)
      await updateOnboardingMutation.mutateAsync({
        current_step: TOTAL_ONBOARDING_STEPS,
        assistant_message: null,
        selected_nudge: null,
        card_steps: null,
        upload_steps: null,
        // Keep filter IDs - they're useful for reference and don't need to be cleared
      });

      // Mark onboarding as complete in context
      setOnboardingComplete(true);

      // Clear ALL conversation state so next message starts fresh
      // This will pick up the default filter we just set
      await startNewConversation();

      setShowLayout(true);
    }
  };

  const handleStepBack = async () => {
    if (currentStep > 0) {
      const prevStep = currentStep - 1;
      setCurrentStep(prevStep);
      // Save step to backend
      await updateOnboardingMutation.mutateAsync({ current_step: prevStep });
    }
  };

  const handleSkipOnboarding = async () => {
    // Skip onboarding by marking it as complete in backend
    await updateOnboardingMutation.mutateAsync({
      current_step: TOTAL_ONBOARDING_STEPS,
      assistant_message: null,
      selected_nudge: null,
      card_steps: null,
      upload_steps: null,
      openrag_docs_filter_id: null,
      user_doc_filter_id: null,
    });
    
    // Mark onboarding as complete in context
    setOnboardingComplete(true);
    // Store the OpenRAG docs filter as default for new conversations
    await storeDefaultFilterForNewConversations(false);
    setShowLayout(true);
  };

  // List of paths with smaller max-width
  const smallWidthPaths = ["/settings", "/upload"];
  const isSmallWidthPath = smallWidthPaths.some((path) =>
    pathname.startsWith(path),
  );

  const x = showLayout ? "0px" : `calc(-${SIDEBAR_WIDTH / 2}px + 50vw)`;
  const y = showLayout ? "0px" : `calc(-${HEADER_HEIGHT / 2}px + 50vh)`;
  const translateY = showLayout ? "0px" : `-50vh`;
  const translateX = showLayout ? "0px" : `-50vw`;

  // For all other pages, render with Langflow-styled navigation and task menu
  return (
    <>
      <AnimatedConditional
        className="[grid-area:header] bg-background border-b"
        vertical
        slide
        isOpen={showLayout}
        delay={ANIMATION_DURATION / 2}
      >
        <Header />
      </AnimatedConditional>

      {/* Sidebar Navigation */}
      <AnimatedConditional
        isOpen={showLayout}
        slide
        className={`border-r bg-background overflow-hidden [grid-area:nav] w-[${SIDEBAR_WIDTH}px]`}
      >
        {showLayout && (
          <Navigation
            conversations={conversations}
            isConversationsLoading={isConversationsLoading}
            onNewConversation={handleNewConversation}
          />
        )}
      </AnimatedConditional>

      {/* Main Content */}
      <main className="overflow-hidden w-full flex items-center justify-center [grid-area:main]">
        <motion.div
          initial={{
            width: showLayout ? "100%" : "100vw",
            height: showLayout ? "100%" : "100vh",
            x: x,
            y: y,
            translateX: translateX,
            translateY: translateY,
          }}
          animate={{
            width: showLayout ? "100%" : "850px",
            borderRadius: showLayout ? "0" : "16px",
            border: showLayout ? "0" : "1px solid hsl(var(--border))",
            height: showLayout ? "100%" : "800px",
            x: x,
            y: y,
            translateX: translateX,
            translateY: translateY,
          }}
          transition={{
            duration: ANIMATION_DURATION,
            ease: "easeOut",
          }}
          className={cn(
            "flex h-full w-full max-w-full max-h-full items-center justify-center overflow-y-auto",
            !showLayout &&
              "absolute max-h-[calc(100vh-190px)] shadow-[0px_2px_4px_-2px_#0000001A,0px_4px_6px_-1px_#0000001A]",
            showLayout && !isOnChatPage && "bg-background",
          )}
        >
          <div
            className={cn(
              "h-full bg-background w-full",
              showLayout && !isOnChatPage && "p-6 container",
              showLayout && isSmallWidthPath && "max-w-[850px] ml-0",
              !showLayout && "p-0 py-2",
            )}
          >
            <motion.div
              initial={{
                opacity: showLayout ? 1 : 0,
              }}
              animate={{
                opacity: "100%",
              }}
              transition={{
                duration: ANIMATION_DURATION,
                ease: "easeOut",
                delay: ANIMATION_DURATION,
              }}
              className={cn("w-full h-full")}
            >
              {showLayout && (
                <div className={cn("w-full h-full", !showLayout && "hidden")}>
                  {children}
                </div>
              )}
              {!showLayout && (
                <OnboardingContent
                  handleStepComplete={handleStepComplete}
                  handleStepBack={handleStepBack}
                  currentStep={currentStep}
                />
              )}
            </motion.div>
          </div>
        </motion.div>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: showLayout ? 0 : 1, y: showLayout ? 20 : 0 }}
          transition={{ duration: ANIMATION_DURATION, ease: "easeOut" }}
          className={cn("absolute bottom-6 left-0 right-0")}
        >
          <ProgressBar
            currentStep={currentStep}
            totalSteps={TOTAL_ONBOARDING_STEPS}
            onSkip={handleSkipOnboarding}
          />
        </motion.div>
      </main>
    </>
  );
}
