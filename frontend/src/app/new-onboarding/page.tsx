"use client";

import { Suspense, useState } from "react";
import { DoclingHealthBanner } from "@/components/docling-health-banner";
import { ProtectedRoute } from "@/components/protected-route";
import { OnboardingContent } from "./components/onboarding-content";
import { ProgressBar } from "./components/progress-bar";

const TOTAL_STEPS = 4;

function NewOnboardingPage() {
	const [currentStep, setCurrentStep] = useState(0);

	const handleStepComplete = () => {
		if (currentStep < TOTAL_STEPS - 1) {
			setCurrentStep(currentStep + 1);
		}
	};

	return (
		<div className="min-h-dvh w-full flex gap-5 flex-col items-center justify-center bg-primary-foreground relative p-4">
			<DoclingHealthBanner className="absolute top-0 left-0 right-0 w-full z-20" />

			{/* Chat-like content area */}
			<div className="flex flex-col items-center gap-5 w-full max-w-3xl z-10">
				<div className="w-full h-[872px] bg-background border rounded-lg p-4 shadow-sm overflow-y-auto">
					<OnboardingContent handleStepComplete={handleStepComplete} currentStep={currentStep} />
				</div>

				<ProgressBar currentStep={currentStep} totalSteps={TOTAL_STEPS} />
			</div>
		</div>
	);
}

export default function ProtectedNewOnboardingPage() {
	return (
		<ProtectedRoute>
			<Suspense fallback={<div>Loading...</div>}>
				<NewOnboardingPage />
			</Suspense>
		</ProtectedRoute>
	);
}
