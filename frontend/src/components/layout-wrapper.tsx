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

export function LayoutWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { isMenuOpen } = useTask();
  const { isPanelOpen } = useKnowledgeFilter();
  const { isLoading, isAuthenticated, isNoAuthMode } = useAuth();

  const { data: settings, isLoading: isSettingsLoading } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });
  const {
    data: health,
    isLoading: isHealthLoading,
    isError,
  } = useDoclingHealthQuery();

  // List of paths that should not show navigation
  const authPaths = ["/login", "/auth/callback"];
  const isAuthPage = authPaths.includes(pathname);
  const isOnKnowledgePage = pathname.startsWith("/knowledge");

  const isUnhealthy = health?.status === "unhealthy" || isError;
  const isBannerVisible = !isHealthLoading && isUnhealthy;

  // Show loading state when backend isn't ready
  if (isLoading || isSettingsLoading || !settings) {
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
