"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
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
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { AnimatedConditional } from "./animated-conditional";
import { ChatRenderer } from "./chat-renderer";

export function LayoutWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { isMenuOpen, closeMenu } = useTask();
  const { isPanelOpen, closePanelOnly } = useKnowledgeFilter();

  // Only one panel can be open at a time
  useEffect(() => {
    if (isMenuOpen) closePanelOnly();
  }, [isMenuOpen, closePanelOnly]);
  useEffect(() => {
    if (isPanelOpen) closeMenu();
  }, [isPanelOpen, closeMenu]);
  const { isLoading, isAuthenticated, isNoAuthMode } = useAuth();
  const { isOnboardingComplete } = useChat();

  // List of paths that should not show navigation
  const authPaths = ["/login", "/auth/callback"];
  const isAuthPage = authPaths.includes(pathname);

  // Redirect to login when not authenticated (and not in no-auth mode)
  useEffect(() => {
    if (!isLoading && !isAuthenticated && !isNoAuthMode && !isAuthPage) {
      const redirectUrl = `/login?redirect=${encodeURIComponent(pathname)}`;
      router.push(redirectUrl);
    }
  }, [isLoading, isAuthenticated, isNoAuthMode, isAuthPage, pathname, router]);

  // Call all hooks unconditionally (React rules)
  // But disable queries for auth pages to prevent unnecessary requests
  const { data: settings, isLoading: isSettingsLoading } = useGetSettingsQuery({
    enabled: !isAuthPage && (isAuthenticated || isNoAuthMode),
  });

  const { isUnhealthy: isDoclingUnhealthy } = useDoclingHealth();
  const { isUnhealthy: isProviderUnhealthy } = useProviderHealth();

  // For auth pages, render immediately without navigation
  // This prevents the main layout from flashing
  if (isAuthPage) {
    return <div className="h-full">{children}</div>;
  }

  const isOnKnowledgePage = pathname.startsWith("/knowledge");

  const isSettingsLoadingOrError = isSettingsLoading || !settings;

  // Show loading state when backend isn't ready or when not authenticated (redirect will happen)
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

  // For all other pages, render with Langflow-styled navigation and task menu
  return (
    <div className="h-screen w-screen flex items-center justify-center bg-muted dark:bg-black">
      <div
        className={cn(
          "app-grid-arrangement relative",
          isPanelOpen && isOnKnowledgePage && !isMenuOpen && "filters-open",
          isMenuOpen && "notifications-open",
        )}
      >
        <div className="w-full z-10 bg-background [grid-area:banner]">
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

        <ChatRenderer settings={settings}>{children}</ChatRenderer>

        {/* Right Panel — task notifications or knowledge filter, one at a time */}
        <aside className="overflow-y-auto overflow-x-hidden [grid-area:right-panel]">
          <AnimatePresence>
            {isMenuOpen && (
              <motion.div
                key="notifications"
                className="h-full"
                initial={{ x: "100%" }}
                animate={{ x: 0 }}
                exit={{ x: "100%", transition: { duration: 0 } }}
                transition={{ duration: 0.25, ease: "easeOut" }}
              >
                <TaskNotificationMenu />
              </motion.div>
            )}
            {isPanelOpen && !isMenuOpen && (
              <motion.div
                key="filters"
                className="h-full"
                initial={{ x: "100%" }}
                animate={{ x: 0 }}
                exit={{ x: "100%", transition: { duration: 0 } }}
                transition={{ duration: 0.25, ease: "easeOut" }}
              >
                <KnowledgeFilterPanel />
              </motion.div>
            )}
          </AnimatePresence>
        </aside>
      </div>
    </div>
  );
}
