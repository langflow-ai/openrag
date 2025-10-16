import { AnimatePresence, motion } from "framer-motion";
import { CheckIcon } from "lucide-react";
import { useEffect } from "react";
import { AnimatedProcessingIcon } from "@/components/ui/animated-processing-icon";
import { cn } from "@/lib/utils";

export function AnimatedProviderSteps({
	currentStep,
	setCurrentStep,
}: {
	currentStep: number;
	setCurrentStep: (step: number) => void;
}) {
	const steps = [
		"Setting up your model provider",
		"Defining schema",
		"Configuring Langflow",
		"Ingesting sample data",
	];

	useEffect(() => {
		if (currentStep < steps.length - 1) {
			const interval = setInterval(() => {
				setCurrentStep(currentStep + 1);
			}, 1000);
			return () => clearInterval(interval);
		}
	}, [currentStep, setCurrentStep]);

	const isDone = currentStep >= steps.length;

	return (
		<div className="flex flex-col gap-2">
			<div className="flex items-center gap-2">
				<div
					className={cn(
						"transition-all duration-150 relative",
						isDone ? "w-3.5 h-3.5" : "w-1.5 h-2.5",
					)}
				>
					<CheckIcon className={cn("text-accent-emerald-foreground shrink-0 w-3.5 h-3.5 absolute inset-0 transition-all duration-150", isDone ? "opacity-100" : "opacity-0")} />
					<AnimatedProcessingIcon className={cn("text-current shrink-0 absolute inset-0 transition-all duration-150", isDone ? "opacity-0" : "opacity-100")} />
				</div>

				<span className="text-mmd font-medium text-muted-foreground">
					{isDone ? "Done" : "Thinking"}
				</span>
			</div>
            <div className="overflow-hidden">
			<AnimatePresence>
				{!isDone && (
					<motion.div
						initial={{ opacity: 1, y: 0, height: "auto" }}
						exit={{ opacity: 0, y: -24, height: 0 }}
						transition={{ duration: 0.4, ease: "easeInOut" }}
						className="flex items-center gap-5 overflow-hidden relative h-6"
					>
						<div className="w-px h-6 bg-border" />
						<AnimatePresence mode="popLayout" initial={false}>
							<motion.span
								key={currentStep}
								initial={{ y: 24, opacity: 0 }}
								animate={{ y: 0, opacity: 1 }}
								exit={{ y: -24, opacity: 0 }}
								transition={{ duration: 0.3, ease: "easeInOut" }}
								className="text-mmd font-medium text-primary"
							>
								{steps[currentStep]}
							</motion.span>
						</AnimatePresence>
					</motion.div>
				)}
			</AnimatePresence></div>
		</div>
	);
}
