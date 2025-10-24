"use client";

import { Suspense, useState } from "react";
import { ProtectedRoute } from "@/components/protected-route";
import { DoclingHealthBanner } from "@/components/docling-health-banner";
import { DotPattern } from "@/components/ui/dot-pattern";
import { cn } from "@/lib/utils";
import { OnboardingStep } from "./components/onboarding-step";
import { ProgressBar } from "./components/progress-bar";
import OnboardingCard from "../onboarding/components/onboarding-card";

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
                  onClick={() => window.location.href = "/chat"}
                  className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
                >
                  Go to Chat
                </button>
              </div>
            </OnboardingStep>
          </div>
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
