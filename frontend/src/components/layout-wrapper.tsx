"use client";

import { Bell, Loader2 } from "lucide-react";
import { usePathname } from "next/navigation";
import {
  useGetConversationsQuery,
  type ChatConversation,
} from "@/app/api/queries/useGetConversationsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { DoclingHealthBanner } from "@/components/docling-health-banner";
import { KnowledgeFilterPanel } from "@/components/knowledge-filter-panel";
import Logo from "@/components/logo/logo";
import { Navigation } from "@/components/navigation";
import { TaskNotificationMenu } from "@/components/task-notification-menu";
import { UserNav } from "@/components/user-nav";
import { useAuth } from "@/contexts/auth-context";
import { useChat } from "@/contexts/chat-context";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
// import { GitHubStarButton } from "@/components/github-star-button"
// import { DiscordLink } from "@/components/discord-link"
import { useTask } from "@/contexts/task-context";
import { useDoclingHealthQuery } from "@/src/app/api/queries/useDoclingHealthQuery";
import { cn } from "@/lib/utils";

export function LayoutWrapper({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { tasks, isMenuOpen, toggleMenu } = useTask();
  const { isPanelOpen } = useKnowledgeFilter();
  const { isLoading, isAuthenticated, isNoAuthMode } = useAuth();
  const {
    endpoint,
    refreshTrigger,
    refreshConversations,
    startNewConversation,
  } = useChat();
  const { isLoading: isSettingsLoading } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });
  const {
    data: health,
    isLoading: isHealthLoading,
    isError,
  } = useDoclingHealthQuery();

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
  const authPaths = ["/login", "/auth/callback", "/onboarding", "/new-onboarding"];
  const isAuthPage = authPaths.includes(pathname);
  const isOnKnowledgePage = pathname.startsWith("/knowledge");

  // List of paths with smaller max-width
  const smallWidthPaths = ["/settings/connector/new"];
  const isSmallWidthPath = smallWidthPaths.includes(pathname);

  // Calculate active tasks for the bell icon
  const activeTasks = tasks.filter(
    task =>
      task.status === "pending" ||
      task.status === "running" ||
      task.status === "processing"
  );

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
    <div
      className={cn(
        "app-grid-arrangement",
        isBannerVisible && "banner-visible",
        isPanelOpen && isOnKnowledgePage && !isMenuOpen && "filters-open",
        isMenuOpen && "notifications-open"
      )}
    >
      <div className="w-full [grid-area:banner]">
        <DoclingHealthBanner className="w-full" />
      </div>
      <header className="header-arrangement bg-background [grid-area:header]">
        <div className="header-start-display px-[16px]">
          {/* Logo/Title */}
          <div className="flex items-center">
            <Logo className="fill-primary" width={24} height={22} />
            <span className="text-lg font-semibold pl-2.5">OpenRAG</span>
          </div>
        </div>
        <div className="header-end-division">
          <div className="justify-end flex items-center">
            {/* Knowledge Filter Dropdown */}
            {/* <KnowledgeFilterDropdown
              selectedFilter={selectedFilter}
              onFilterSelect={setSelectedFilter}
            /> */}

            {/* GitHub Star Button */}
            {/* <GitHubStarButton repo="phact/openrag" /> */}

            {/* Discord Link */}
            {/* <DiscordLink inviteCode="EqksyE2EX9" /> */}

            {/* Task Notification Bell */}
            <button
              onClick={toggleMenu}
              className="relative h-8 w-8 hover:bg-muted rounded-lg flex items-center justify-center"
            >
              <Bell size={16} className="text-muted-foreground" />
              {activeTasks.length > 0 && (
                <div className="header-notifications" />
              )}
            </button>

            {/* Separator */}
            <div className="w-px h-6 bg-border mx-3" />

            <UserNav />
          </div>
        </div>
      </header>

      {/* Sidebar Navigation */}
      <aside className="bg-background border-r overflow-hidden [grid-area:nav]">
        <Navigation
          conversations={conversations}
          isConversationsLoading={isConversationsLoading}
          onNewConversation={handleNewConversation}
        />
      </aside>

      {/* Main Content */}
      <main className="overflow-y-auto [grid-area:main]">
        <div
          className={cn(
            "p-6 h-full container",
            isSmallWidthPath && "max-w-[850px] ml-0"
          )}
        >
          {children}
        </div>
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
  );
}
