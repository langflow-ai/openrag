"use client";

import { Bell, Loader2 } from "lucide-react";
import { usePathname } from "next/navigation";
import {
  useGetConversationsQuery,
  type ChatConversation,
} from "@/app/api/queries/useGetConversationsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { KnowledgeFilterPanel } from "@/components/knowledge-filter-panel";
import Logo from "@/components/logo/logo";
import { Navigation } from "@/components/navigation";
import { TaskNotificationMenu } from "@/components/task-notification-menu";
import { Button } from "@/components/ui/button";
import { UserNav } from "@/components/user-nav";
import { useAuth } from "@/contexts/auth-context";
import { useChat } from "@/contexts/chat-context";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
// import { GitHubStarButton } from "@/components/github-star-button"
// import { DiscordLink } from "@/components/discord-link"
import { useTask } from "@/contexts/task-context";

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
  const { isLoading: isSettingsLoading, data: settings } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

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
  const authPaths = ["/login", "/auth/callback", "/onboarding"];
  const isAuthPage = authPaths.includes(pathname);

  // Calculate active tasks for the bell icon
  const activeTasks = tasks.filter(
    task =>
      task.status === "pending" ||
      task.status === "running" ||
      task.status === "processing"
  );

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

  if (isAuthPage || (settings && !settings.edited)) {
    // For auth pages, render without navigation
    return <div className="h-full">{children}</div>;
  }

  // For all other pages, render with Langflow-styled navigation and task menu
  return (
    <div className="h-full relative">
      <header className="header-arrangement bg-background sticky top-0 z-50 h-10">
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
              className="h-8 w-8 hover:bg-muted rounded-lg flex items-center justify-center"
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
      <div className="side-bar-arrangement bg-background fixed left-0 top-[40px] bottom-0 md:flex hidden pt-1">
        <Navigation
          conversations={conversations}
          isConversationsLoading={isConversationsLoading}
          onNewConversation={handleNewConversation}
        />
      </div>
      <main
        className={`md:pl-72 transition-all duration-300 overflow-y-auto h-[calc(100vh-53px)] ${
          isMenuOpen && isPanelOpen
            ? "md:pr-[728px]"
            : // Both open: 384px (menu) + 320px (KF panel) + 24px (original padding)
            isMenuOpen
            ? "md:pr-96"
            : // Only menu open: 384px
            isPanelOpen
            ? "md:pr-80"
            : // Only KF panel open: 320px
              "md:pr-0" // Neither open: 24px
        }`}
      >
        <div className="container py-6 lg:py-8 px-4 lg:px-6">{children}</div>
      </main>
      <TaskNotificationMenu />
      <KnowledgeFilterPanel />
    </div>
  );
}
