"use client";

import { AnimatePresence, motion } from "framer-motion";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useConsoleStatusQuery } from "@/app/api/queries/useConsoleStatusQuery";
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
import { useIsCloudBrand } from "@/contexts/brand-context";
import { useChat } from "@/contexts/chat-context";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useTask } from "@/contexts/task-context";
import { usePortal } from "@/hooks/use-portal";
import { ANIMATION_DURATION, HEADER_HEIGHT } from "@/lib/constants";
import { isFailureLikeTask } from "@/lib/task-utils";
import { cn } from "@/lib/utils";
import { AnimatedConditional } from "./animated-conditional";
import { ChatRenderer } from "./chat-renderer";
import {
  ConsoleStatusButton,
  ConsoleStatusPanel,
} from "./console-status-panel";
import { Header } from "./header";
import FailedTasksInfo from "./tasks_details";

/** Renders the Console Status button + panel directly into document.body via a
 *  portal so that CSS transforms on ancestor elements (framer-motion sidebar
 *  slide animation) cannot break `position: fixed` viewport anchoring. */
function ConsoleStatusPortal({
  isOpen,
  onToggle,
  onClose,
  overallStatus,
}: {
  isOpen: boolean;
  onToggle: () => void;
  onClose: () => void;
  overallStatus?: import("@/app/api/queries/useConsoleStatusQuery").ComponentState;
}) {
  const host = usePortal("console-status-portal");
  if (!host) return null;
  return createPortal(
    <>
      <ConsoleStatusButton
        onClick={onToggle}
        isOpen={isOpen}
        overallStatus={overallStatus}
      />
      {isOpen && <ConsoleStatusPanel onClose={onClose} />}
    </>,
    host,
  );
}

export function LayoutWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { tasks, isMenuOpen } = useTask();
  const isCloudBrand = useIsCloudBrand();
  const { isPanelOpen, panelMode, closePanelOnly } = useKnowledgeFilter();
  const failedTasks = tasks.filter(isFailureLikeTask);

  const [isStatusOpen, setIsStatusOpen] = useState(false);
  const { data: statusData } = useConsoleStatusQuery({
    enabled: true,
  });

  const isOnKnowledgePage = pathname.startsWith("/knowledge");

  // Close status panel when task menu opens, and vice-versa
  useEffect(() => {
    if (isMenuOpen) {
      closePanelOnly();
      setIsStatusOpen(false);
    }
  }, [isMenuOpen, closePanelOnly]);

  const { isLoading, isAuthenticated, isNoAuthMode, isIbmAuthMode } = useAuth();
  const { isOnboardingComplete } = useChat();

  const authPaths = ["/login", "/auth/callback", "/unauthorized"];
  const isAuthPage = authPaths.includes(pathname);

  useEffect(() => {
    if (isLoading || isAuthenticated || isNoAuthMode || isAuthPage) return;
    if (isIbmAuthMode) {
      router.push("/unauthorized");
      return;
    }
    router.push(`/login?redirect=${encodeURIComponent(pathname)}`);
  }, [
    isLoading,
    isAuthenticated,
    isNoAuthMode,
    isIbmAuthMode,
    isAuthPage,
    pathname,
    router,
  ]);

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
    <div
      className={cn(
        "h-screen w-screen flex flex-col relative",
        isCloudBrand ? "bg-background" : "bg-muted dark:bg-black",
      )}
    >
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
          style={{ width: isRightPanelOpen ? "360px" : "0px" }}
        >
          <div className="w-[360px] h-full shrink-0">
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
                  {panelMode === "ingestion-status" ? (
                    <FailedTasksInfo failedTasks={failedTasks} />
                  ) : (
                    <KnowledgeFilterPanel />
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>

      {/* Console Status — portalled into document.body so fixed positioning
          is always relative to the viewport, not to any transformed ancestor */}
      {isOnboardingComplete && (
        <ConsoleStatusPortal
          isOpen={isStatusOpen}
          onToggle={() => setIsStatusOpen((v) => !v)}
          onClose={() => setIsStatusOpen(false)}
          overallStatus={statusData?.overall_status}
        />
      )}
    </div>
  );
}
