"use client";

import { motion } from "framer-motion";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
	type ChatConversation,
	useGetConversationsQuery,
} from "@/app/api/queries/useGetConversationsQuery";
import type { Settings } from "@/app/api/queries/useGetSettingsQuery";
import { OnboardingContent } from "@/app/onboarding/components/onboarding-content";
import { ProgressBar } from "@/app/onboarding/components/progress-bar";
import { AnimatedConditional } from "@/components/animated-conditional";
import { Header } from "@/components/header";
import { Navigation } from "@/components/navigation";
import { useAuth } from "@/contexts/auth-context";
import { useChat } from "@/contexts/chat-context";
import {
	ANIMATION_DURATION,
	HEADER_HEIGHT,
	ONBOARDING_STEP_KEY,
	SIDEBAR_WIDTH,
	TOTAL_ONBOARDING_STEPS,
} from "@/lib/constants";
import { cn } from "@/lib/utils";

export function ChatRenderer({
	settings,
	children,
}: {
	settings: Settings | undefined;
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

	// Initialize onboarding state based on local storage and settings
	const [currentStep, setCurrentStep] = useState<number>(() => {
		if (typeof window === "undefined") return 0;
		const savedStep = localStorage.getItem(ONBOARDING_STEP_KEY);
		return savedStep !== null ? parseInt(savedStep, 10) : 0;
	});

	const [showLayout, setShowLayout] = useState<boolean>(() => {
		if (typeof window === "undefined") return false;
		const savedStep = localStorage.getItem(ONBOARDING_STEP_KEY);
		// Show layout if settings.edited is true and if no onboarding step is saved
		const isEdited = settings?.edited ?? true;
		return isEdited ? savedStep === null : false;
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

	// Save current step to local storage whenever it changes
	useEffect(() => {
		if (typeof window !== "undefined" && !showLayout) {
			localStorage.setItem(ONBOARDING_STEP_KEY, currentStep.toString());
		}
	}, [currentStep, showLayout]);

	const handleStepComplete = () => {
		if (currentStep < TOTAL_ONBOARDING_STEPS - 1) {
			setCurrentStep(currentStep + 1);
		} else {
			// Onboarding is complete - remove from local storage and show layout
			if (typeof window !== "undefined") {
				localStorage.removeItem(ONBOARDING_STEP_KEY);
			}
			setShowLayout(true);
		}
	};

	const handleSkipOnboarding = () => {
		// Skip onboarding by marking it as complete
		if (typeof window !== "undefined") {
			localStorage.removeItem(ONBOARDING_STEP_KEY);
		}
		setShowLayout(true);
	};

	// List of paths with smaller max-width
	const smallWidthPaths = ["/settings/connector/new"];
	const isSmallWidthPath = smallWidthPaths.includes(pathname);

	const x = showLayout ? "0px" : `calc(-${SIDEBAR_WIDTH / 2}px + 50vw)`;
	const y = showLayout ? "0px" : `calc(-${HEADER_HEIGHT / 2}px + 50vh)`;
	const translateY = showLayout ? "0px" : `-50vh`;
	const translateX = showLayout ? "0px" : `-50vw`;

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
			<main className="overflow-hidden w-full flex items-center justify-center [grid-area:main]">
				<motion.div
					initial={{
						width: showLayout ? "100%" : "100vw",
						height: showLayout ? "100%" : "100vh",
						x: x,
						y: y,
						translateX: translateX,
						translateY: translateY,
					}}
					animate={{
						width: showLayout ? "100%" : "850px",
						borderRadius: showLayout ? "0" : "16px",
						border: showLayout ? "0" : "1px solid #27272A",
						height: showLayout ? "100%" : "800px",
						x: x,
						y: y,
						translateX: translateX,
						translateY: translateY,
					}}
					transition={{
						duration: ANIMATION_DURATION,
						ease: "easeOut",
					}}
					className={cn(
						"flex h-full w-full max-w-full max-h-full items-center justify-center overflow-y-auto",
						!showLayout && "absolute max-h-[calc(100vh-190px)]",
						showLayout && !isOnChatPage && "bg-background",
					)}
				>
					<div
						className={cn(
							"h-full bg-background w-full",
							showLayout && !isOnChatPage && "p-6 container",
							showLayout && isSmallWidthPath && "max-w-[850px] ml-0",
							!showLayout &&
								"w-full bg-card rounded-lg shadow-2xl p-0 py-2",
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
							className={cn("w-full h-full")}
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
					className={cn("absolute bottom-6 left-0 right-0")}
				>
					<ProgressBar
						currentStep={currentStep}
						totalSteps={TOTAL_ONBOARDING_STEPS}
						onSkip={handleSkipOnboarding}
					/>
				</motion.div>
			</main>
		</>
	);
}
