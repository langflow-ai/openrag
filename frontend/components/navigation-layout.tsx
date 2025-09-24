"use client";

import { usePathname } from "next/navigation";
import { useGetConversationsQuery } from "@/app/api/queries/useGetConversationsQuery";
import { KnowledgeFilterDropdown } from "@/components/knowledge-filter-dropdown";
import { ModeToggle } from "@/components/mode-toggle";
import { Navigation } from "@/components/navigation";
import { useAuth } from "@/contexts/auth-context";
import { useChat } from "@/contexts/chat-context";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";

interface NavigationLayoutProps {
  children: React.ReactNode;
}

export function NavigationLayout({ children }: NavigationLayoutProps) {
  const { selectedFilter, setSelectedFilter } = useKnowledgeFilter();
  const pathname = usePathname();
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const {
    endpoint,
    refreshTrigger,
    refreshConversations,
    startNewConversation,
  } = useChat();

  // Only fetch conversations on chat page
  const isOnChatPage = pathname === "/" || pathname === "/chat";
  const { data: conversations = [], isLoading: isConversationsLoading } =
    useGetConversationsQuery(endpoint, refreshTrigger, {
      enabled: isOnChatPage && (isAuthenticated || isNoAuthMode),
    });

  const handleNewConversation = () => {
    refreshConversations();
    startNewConversation();
  };

  return (
    <div className="h-full relative">
      <div className="hidden h-full md:flex md:w-72 md:flex-col md:fixed md:inset-y-0 z-[80] border-r border-border/40">
        <Navigation
          conversations={conversations}
          isConversationsLoading={isConversationsLoading}
          onNewConversation={handleNewConversation}
        />
      </div>
      <main className="md:pl-72">
        <div className="flex flex-col min-h-screen">
          <header className="sticky top-0 z-40 w-full border-b border-border/40 bg-background">
            <div className="container flex h-14 max-w-screen-2xl items-center">
              <div className="mr-4 hidden md:flex">
                <h1 className="text-lg font-semibold tracking-tight">
                  OpenRAG
                </h1>
              </div>
              <div className="flex flex-1 items-center justify-between space-x-2 md:justify-end">
                <div className="w-full flex-1 md:w-auto md:flex-none">
                  {/* Search component could go here */}
                </div>
                <nav className="flex items-center space-x-2">
                  <KnowledgeFilterDropdown
                    selectedFilter={selectedFilter}
                    onFilterSelect={setSelectedFilter}
                  />
                  <ModeToggle />
                </nav>
              </div>
            </div>
          </header>
          <div className="flex-1">
            <div className="container py-6 lg:py-8">{children}</div>
          </div>
        </div>
      </main>
    </div>
  );
}
