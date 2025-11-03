"use client";

import { Loader2 } from "lucide-react";
import { usePathname } from "next/navigation";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { DoclingHealthBanner } from "@/components/docling-health-banner";
import { KnowledgeFilterPanel } from "@/components/knowledge-filter-panel";
import { TaskNotificationMenu } from "@/components/task-notification-menu";
import { useAuth } from "@/contexts/auth-context";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useTask } from "@/contexts/task-context";
import { cn } from "@/lib/utils";
import { useDoclingHealthQuery } from "@/src/app/api/queries/useDoclingHealthQuery";
import { ChatRenderer } from "./chat-renderer";
import AnimatedProcessingIcon from "./ui/animated-processing-icon";

export function LayoutWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { isMenuOpen } = useTask();
  const { isPanelOpen } = useKnowledgeFilter();
  const { isLoading, isAuthenticated, isNoAuthMode } = useAuth();

  // List of paths that should not show navigation
  const authPaths = ["/login", "/auth/callback"];
  const isAuthPage = authPaths.includes(pathname);

  // Call all hooks unconditionally (React rules)
  // But disable queries for auth pages to prevent unnecessary requests
  const { data: settings, isLoading: isSettingsLoading } = useGetSettingsQuery({
    enabled: !isAuthPage && (isAuthenticated || isNoAuthMode),
  });
  const {
    data: health,
    isLoading: isHealthLoading,
    isError,
  } = useDoclingHealthQuery({
    enabled: !isAuthPage,
  });

  // For auth pages, render immediately without navigation
  // This prevents the main layout from flashing
  if (isAuthPage) {
    return <div className="h-full">{children}</div>;
  }

  const isOnKnowledgePage = pathname.startsWith("/knowledge");

  const isUnhealthy = health?.status === "unhealthy" || isError;
  const isBannerVisible = !isHealthLoading && isUnhealthy;
  const isSettingsLoadingOrError = isSettingsLoading || !settings;

  // Show loading state when backend isn't ready
  if (isLoading || (isSettingsLoadingOrError && (isNoAuthMode || isAuthenticated))) {
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
    <div className=" h-screen w-screen flex items-center justify-center">
      <div
        className={cn(
          "app-grid-arrangement bg-black relative",
          isBannerVisible && "banner-visible",
          isPanelOpen && isOnKnowledgePage && !isMenuOpen && "filters-open",
          isMenuOpen && "notifications-open",
        )}
      >
        <div className={`w-full z-10 bg-background [grid-area:banner]`}>
          <DoclingHealthBanner className="w-full" />
        </div>

        <ChatRenderer settings={settings}>{children}</ChatRenderer>

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
