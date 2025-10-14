"use client";

import { Loader2 } from "lucide-react";
import { usePathname } from "next/navigation";
import {
	type ChatConversation,
	useGetConversationsQuery,
} from "@/app/api/queries/useGetConversationsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
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

  const isOnboardingComplete = settings?.edited;

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
				isMenuOpen && "notifications-open",
			)}
		>
			<div className="w-full [grid-area:banner]">
				<DoclingHealthBanner className="w-full" />
			</div>
			<Header />

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
						isSmallWidthPath && "max-w-[850px] ml-0",
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
