import { AnimatePresence, motion } from "motion/react";
import { cn } from "@/lib/utils";

export default function Nudges({
	nudges,
	onboarding,
	handleSuggestionClick,
}: {
	nudges: string[];
	onboarding?: boolean;
	handleSuggestionClick: (suggestion: string) => void;
}) {
	return (
		<div className="flex-shrink-0 h-12 w-full overflow-hidden">
			<AnimatePresence>
				{nudges.length > 0 && (
					<motion.div
						initial={{ opacity: 0, y: 20 }}
						animate={{ opacity: 1, y: 0 }}
						exit={{ opacity: 0, y: 20 }}
						transition={{
							duration: 0.2,
							ease: "easeInOut",
						}}
					>
						<div
							className={
								onboarding
									? "relative flex"
									: "relative px-6 pt-4 flex justify-center"
							}
						>
							<div className="w-full max-w-[75%]">
								<div className="flex gap-3 justify-start overflow-x-auto scrollbar-hide">
									{nudges.map((suggestion: string, index: number) => (
										<button
											key={index}
											onClick={() => handleSuggestionClick(suggestion)}
											className={cn(
												onboarding
													? "bg-background hover:bg-background/50 text-foreground border"
													: "bg-muted hover:bg-muted/50 text-placeholder-foreground hover:text-foreground",
												"px-2 py-1.5 rounded-lg text-sm transition-colors whitespace-nowrap",
											)}
										>
											{suggestion}
										</button>
									))}
								</div>
								{/* Fade out gradient on the right */}
								<div className="absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-background to-transparent pointer-events-none"></div>
							</div>
						</div>
					</motion.div>
				)}
			</AnimatePresence>
		</div>
	);
}
