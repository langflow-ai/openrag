"use client";

import { motion } from "framer-motion";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
	type ChatConversation,
	useGetConversationsQuery,
} from "@/app/api/queries/useGetConversationsQuery";
import type { Settings } from "@/app/api/queries/useGetSettingsQuery";
import { OnboardingContent } from "@/app/new-onboarding/components/onboarding-content";
import { ProgressBar } from "@/app/new-onboarding/components/progress-bar";
import { AnimatedConditional } from "@/components/animated-conditional";
import { Header } from "@/components/header";
import { Navigation } from "@/components/navigation";
import { useAuth } from "@/contexts/auth-context";
import { useChat } from "@/contexts/chat-context";
import {
	ANIMATION_DURATION,
	HEADER_HEIGHT,
	SIDEBAR_WIDTH,
	TOTAL_ONBOARDING_STEPS,
} from "@/lib/constants";
import { cn } from "@/lib/utils";

export function ChatRenderer({
	settings,
	children,
}: {
	settings: Settings;
	children: React.ReactNode;
}) {
	const pathname = usePathname();
	const { isAuthenticated, isNoAuthMode } = useAuth();
	const {
		endpoint,
		refreshTrigger,
		refreshConversations,
		startNewConversation,
	} = useChat();

	// Onboarding animation state
	const [showLayout, setShowLayout] = useState(!!settings?.edited);
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

	const [currentStep, setCurrentStep] = useState(0);

	const handleStepComplete = () => {
		if (currentStep < TOTAL_ONBOARDING_STEPS - 1) {
			setCurrentStep(currentStep + 1);
		} else {
			setShowLayout(true);
		}
	};
	// List of paths with smaller max-width
	const smallWidthPaths = ["/settings/connector/new"];
	const isSmallWidthPath = smallWidthPaths.includes(pathname);

	// For all other pages, render with Langflow-styled navigation and task menu
	return (
		<>
			<AnimatedConditional
				className="[grid-area:header] bg-background border-b"
				vertical
				slide
				isOpen={showLayout}
				delay={ANIMATION_DURATION / 2}
			>
				<Header />
			</AnimatedConditional>

			{/* Sidebar Navigation */}
			<AnimatedConditional
				isOpen={showLayout}
				slide
				className={`border-r bg-background overflow-hidden [grid-area:nav] w-[${SIDEBAR_WIDTH}px]`}
			>
				<Navigation
					conversations={conversations}
					isConversationsLoading={isConversationsLoading}
					onNewConversation={handleNewConversation}
				/>
			</AnimatedConditional>

			{/* Main Content */}
			<main className="overflow-visible w-full flex items-center justify-center [grid-area:main]">
				<motion.div
					initial={
						{
									width: !showLayout ? "100vh" : "100%",
									height: !showLayout ? "100vh" : "100%",
									y: showLayout
										? "0px"
										: `-${HEADER_HEIGHT}px`,
									x: showLayout
										? "0px"
										: `0px`,
								}
					}
					animate={{
						width: showLayout ? "100%" : "60%",
						borderRadius: showLayout ? "0" : "16px",
						border: showLayout ? "0" : "1px solid #27272A",
						height: showLayout ? "100%" : "60%",
						y: showLayout ? "0px" : `-${HEADER_HEIGHT / 2}px`,
						x: showLayout ? "0px" : `-${SIDEBAR_WIDTH / 2}px`,
					}}
					transition={{
						duration: ANIMATION_DURATION,
						ease: "easeOut",
					}}
					className={cn(
						"flex h-full w-full items-center justify-center overflow-hidden ",
					)}
				>
					<div
						className={cn(
							"h-full bg-background",
							showLayout && "p-6 container",
							showLayout && isSmallWidthPath && "max-w-[850px] ml-0",
							!showLayout &&
								"w-full bg-card rounded-lg shadow-2xl p-8 overflow-y-auto",
						)}
					>
						<motion.div
							initial={{
								opacity: showLayout ? 1 : 0,
							}}
							animate={{
								opacity: "100%",
							}}
							transition={{
								duration: ANIMATION_DURATION,
								ease: "easeOut",
								delay: ANIMATION_DURATION,
							}}
							className={cn("w-full h-full 0v")}
						>
							<div className={cn("w-full h-full", !showLayout && "hidden")}>
								{children}
							</div>
							{!showLayout && (
								<OnboardingContent
									handleStepComplete={handleStepComplete}
									currentStep={currentStep}
								/>
							)}
						</motion.div>
					</div>
				</motion.div>
				<motion.div
					initial={{ opacity: 0, y: 20 }}
					animate={{ opacity: showLayout ? 0 : 1, y: showLayout ? 20 : 0 }}
					transition={{ duration: ANIMATION_DURATION, ease: "easeOut" }}
					className={cn(
						"absolute bottom-10 left-0 right-0",
						showLayout && "hidden",
					)}
				>
					<ProgressBar
						currentStep={currentStep}
						totalSteps={TOTAL_ONBOARDING_STEPS}
					/>
				</motion.div>
			</main>
		</>
	);
}
