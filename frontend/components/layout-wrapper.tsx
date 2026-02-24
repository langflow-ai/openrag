"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import {
  DoclingHealthBanner,
  useDoclingHealth,
} from "@/components/docling-health-banner";
import AnimatedProcessingIcon from "@/components/icons/animated-processing-icon";
import { KnowledgeFilterPanel } from "@/components/knowledge-filter-panel";
import {
  ProviderHealthBanner,
  useProviderHealth,
} from "@/components/provider-health-banner";
import { TaskNotificationMenu } from "@/components/task-notification-menu";
import { useAuth } from "@/contexts/auth-context";
import { useChat } from "@/contexts/chat-context";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useTask } from "@/contexts/task-context";
import { ANIMATION_DURATION, HEADER_HEIGHT } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { AnimatedConditional } from "./animated-conditional";
import { ChatRenderer } from "./chat-renderer";
import { Header } from "./header";

export function LayoutWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { isMenuOpen, closeMenu } = useTask();
  const { isPanelOpen, closePanelOnly } = useKnowledgeFilter();

  const isOnKnowledgePage = pathname.startsWith("/knowledge");

  // Only one panel can be open at a time
  useEffect(() => {
    if (isMenuOpen) closePanelOnly();
  }, [isMenuOpen, closePanelOnly]);
  useEffect(() => {
    if (isPanelOpen) closeMenu();
  }, [isPanelOpen, closeMenu]);

  const { isLoading, isAuthenticated, isNoAuthMode } = useAuth();
  const { isOnboardingComplete } = useChat();

  const authPaths = ["/login", "/auth/callback"];
  const isAuthPage = authPaths.includes(pathname);

  useEffect(() => {
    if (!isLoading && !isAuthenticated && !isNoAuthMode && !isAuthPage) {
      const redirectUrl = `/login?redirect=${encodeURIComponent(pathname)}`;
      router.push(redirectUrl);
    }
  }, [isLoading, isAuthenticated, isNoAuthMode, isAuthPage, pathname, router]);

  const { data: settings, isLoading: isSettingsLoading } = useGetSettingsQuery({
    enabled: !isAuthPage && (isAuthenticated || isNoAuthMode),
  });

  const { isUnhealthy: isDoclingUnhealthy } = useDoclingHealth();
  const { isUnhealthy: isProviderUnhealthy } = useProviderHealth();

  if (isAuthPage) {
    return <div className="h-full">{children}</div>;
  }

  const isSettingsLoadingOrError = isSettingsLoading || !settings;

  if (
    isLoading ||
    (!isAuthenticated && !isNoAuthMode) ||
    (isSettingsLoadingOrError && (isNoAuthMode || isAuthenticated))
  ) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <AnimatedProcessingIcon className="h-8 w-8 text-current" />
          <p className="text-muted-foreground">Starting OpenRAG...</p>
        </div>
      </div>
    );
  }

  const isRightPanelOpen =
    isMenuOpen || (isPanelOpen && isOnKnowledgePage && !isMenuOpen);

  return (
    <div className="h-screen w-screen flex flex-col bg-muted dark:bg-black relative">
      {/* Banner — full width */}
      <div className="w-full z-10 bg-background">
        <AnimatedConditional
          vertical
          isOpen={isDoclingUnhealthy}
          className="w-full"
        >
          <DoclingHealthBanner />
        </AnimatedConditional>
        {settings?.edited && isOnboardingComplete && (
          <AnimatedConditional
            vertical
            isOpen={isProviderUnhealthy}
            className="w-full"
          >
            <ProviderHealthBanner />
          </AnimatedConditional>
        )}
      </div>

      {/* Header — full width, slides down when onboarding completes */}
      <AnimatedConditional
        vertical
        isOpen={isOnboardingComplete}
        delay={ANIMATION_DURATION / 2}
        className="bg-background border-b shrink-0"
      >
        <div style={{ height: HEADER_HEIGHT }}>
          <Header />
        </div>
      </AnimatedConditional>

      {/* Body row: nav + main content + right panel */}
      <div className="flex-1 min-h-0 flex flex-row overflow-hidden">
        <ChatRenderer settings={settings}>{children}</ChatRenderer>

        {/* Right panel — slides in from the right, pushes main content */}
        <div
          className={cn(
            "overflow-hidden bg-sidebar flex flex-row justify-end transition-[width] duration-200 ease-linear",
            isRightPanelOpen && "border-l border-sidebar-border",
          )}
          style={{ width: isRightPanelOpen ? "320px" : "0px" }}
        >
          <div className="w-[320px] h-full shrink-0">
            <AnimatePresence mode="wait">
              {isMenuOpen && (
                <motion.div
                  key="notifications"
                  className="h-full"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.15 }}
                >
                  <TaskNotificationMenu />
                </motion.div>
              )}
              {isPanelOpen && !isMenuOpen && isOnKnowledgePage && (
                <motion.div
                  key="filters"
                  className="h-full"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.15 }}
                >
                  <KnowledgeFilterPanel />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </div>
  );
}
