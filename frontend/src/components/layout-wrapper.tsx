"use client";

import { motion } from "framer-motion";
import { Loader2 } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  type ChatConversation,
  useGetConversationsQuery,
} from "@/app/api/queries/useGetConversationsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { AnimatedConditional } from "@/components/animated-conditional";
import { DoclingHealthBanner } from "@/components/docling-health-banner";
import { Header } from "@/components/header";
import { KnowledgeFilterPanel } from "@/components/knowledge-filter-panel";
import { Navigation } from "@/components/navigation";
import { TaskNotificationMenu } from "@/components/task-notification-menu";
import { useAuth } from "@/contexts/auth-context";
import { useChat } from "@/contexts/chat-context";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useTask } from "@/contexts/task-context";
import { cn } from "@/lib/utils";
import { useDoclingHealthQuery } from "@/src/app/api/queries/useDoclingHealthQuery";

export function LayoutWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { isMenuOpen } = useTask();
  const { isPanelOpen } = useKnowledgeFilter();
  const { isLoading, isAuthenticated, isNoAuthMode } = useAuth();
  const {
    endpoint,
    refreshTrigger,
    refreshConversations,
    startNewConversation,
  } = useChat();
  const { data: settings, isLoading: isSettingsLoading } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });
  const {
    data: health,
    isLoading: isHealthLoading,
    isError,
  } = useDoclingHealthQuery();

  // Onboarding animation state
  const [showLayout, setShowLayout] = useState(false);
  const isOnboardingComplete = settings?.edited;

  useEffect(() => {
    if (!isOnboardingComplete) {
      // Wait 3 seconds before showing the layout
      const timer = setTimeout(() => {
        setShowLayout(true);
      }, 3000);
      return () => clearTimeout(timer);
    } else {
      // If onboarding is complete, show layout immediately
      setShowLayout(true);
    }
  }, [isOnboardingComplete]);

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

  // List of paths that should not show navigation
  const authPaths = ["/login", "/auth/callback"];
  const isAuthPage = authPaths.includes(pathname);
  const isOnKnowledgePage = pathname.startsWith("/knowledge");

  // List of paths with smaller max-width
  const smallWidthPaths = ["/settings/connector/new"];
  const isSmallWidthPath = smallWidthPaths.includes(pathname);

  const isUnhealthy = health?.status === "unhealthy" || isError;
  const isBannerVisible = !isHealthLoading && isUnhealthy;

  // Show loading state when backend isn't ready
  if (isLoading || isSettingsLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin" />
          <p className="text-muted-foreground">Starting OpenRAG...</p>
        </div>
      </div>
    );
  }

  if (isAuthPage) {
    // For auth pages, render without navigation
    return <div className="h-full">{children}</div>;
  }

  // For all other pages, render with Langflow-styled navigation and task menu
  return (
    <div className=" h-screen w-screen flex items-center justify-center">
      <div
        className={cn(
          "app-grid-arrangement bg-black",
          !isBannerVisible && "banner-visible",
          isPanelOpen && isOnKnowledgePage && !isMenuOpen && "filters-open",
          isMenuOpen && "notifications-open",
        )}
      >
        <div className="w-full bg-background hidden [grid-area:banner]">
          <DoclingHealthBanner className="w-full" />
        </div>

        <AnimatedConditional
          className="[grid-area:header] bg-background border-b"
          vertical
          isOpen={showLayout}
		  delay={0.2}
        >
          <Header />
        </AnimatedConditional>

        {/* Sidebar Navigation */}
        <AnimatedConditional
          isOpen={showLayout}
          className="border-r bg-background overflow-hidden [grid-area:nav] w-[380px]"
        >
          <Navigation
            conversations={conversations}
            isConversationsLoading={isConversationsLoading}
            onNewConversation={handleNewConversation}
          />
        </AnimatedConditional>

        {/* Main Content */}
        <main className="overflow-y-auto w-full flex items-center justify-center [grid-area:main]">
          <motion.div
            layout
            initial={
              !isOnboardingComplete
                ? {
                    width: "100%",
                    height: "100%",
                  }
                : undefined
            }
            animate={{
              width: showLayout ? "100%" : "60%",
              borderRadius: showLayout ? "0" : "16px",
              border: showLayout ? "0" : "1px solid #27272A",
              height: showLayout ? "100%" : "60%",
            }}
            transition={{
              duration: 0.4,
              ease: "easeOut",
            }}
            className={cn("flex h-full w-full items-center justify-center overflow-hidden ")}
          >
            <div
              className={cn(
                "h-full bg-background",
                showLayout && "p-6 container",
                showLayout && isSmallWidthPath && "max-w-[850px] ml-0",
                !showLayout && "w-full bg-card rounded-lg shadow-2xl p-8",
              )}
            >
              <motion.div
                initial={
                  !isOnboardingComplete
                    ? {
                        opacity: "0%",
                        y: "0px",
                      }
                    : undefined
                }
                animate={{
                  opacity: "100%",
                  y: "20px",
                }}
                transition={{
                  duration: 0.4,
                  ease: "easeInOut",
                  delay: 0.4,
                }}
                className={cn("w-full h-full")}
              >
                {children}
              </motion.div>
            </div>
          </motion.div>
        </main>

        {/* Task Notifications Panel */}
        <aside className="overflow-y-auto overflow-x-hidden [grid-area:notifications]">
          {isMenuOpen && <TaskNotificationMenu />}
        </aside>

        {/* Knowledge Filter Panel */}
        <aside className="overflow-y-auto overflow-x-hidden [grid-area:filters]">
          {isPanelOpen && <KnowledgeFilterPanel />}
        </aside>
      </div>
    </div>
  );
}
