"use client";

import OnboardingCard from "@/app/onboarding/components/onboarding-card";
import { OnboardingStep } from "./onboarding-step";

export function OnboardingContent({ handleStepComplete, currentStep }: { handleStepComplete: () => void, currentStep: number }) {
	return (
		<div className="space-y-6">
			<OnboardingStep
				isVisible={currentStep >= 0}
				isCompleted={currentStep > 0}
				text="Let's get started by setting up your model provider."
			>
				<OnboardingCard onComplete={handleStepComplete} />
			</OnboardingStep>

			<OnboardingStep
				isVisible={currentStep >= 1}
				isCompleted={currentStep > 1}
				text="Step 1: Configure your settings"
			>
				<div className="space-y-4">
					<p className="text-muted-foreground">
						Let's configure some basic settings for your account.
					</p>
					<button
						onClick={handleStepComplete}
						className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
					>
						Continue
					</button>
				</div>
			</OnboardingStep>

			<OnboardingStep
				isVisible={currentStep >= 2}
				isCompleted={currentStep > 2}
				text="Step 2: Connect your model"
			>
				<div className="space-y-4">
					<p className="text-muted-foreground">
						Choose and connect your preferred AI model provider.
					</p>
					<button
						onClick={handleStepComplete}
						className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
					>
						Continue
					</button>
				</div>
			</OnboardingStep>

			<OnboardingStep
				isVisible={currentStep >= 3}
				isCompleted={currentStep > 3}
				text="Step 3: You're all set!"
			>
				<div className="space-y-4">
					<p className="text-muted-foreground">
						Your account is ready to use. Let's start chatting!
					</p>
					<button
						onClick={handleStepComplete}
						className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
					>
						Go to Chat
					</button>
				</div>
			</OnboardingStep>
		</div>
	);
}
