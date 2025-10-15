"use client";

import { Suspense } from "react";
import { DoclingHealthBanner, useDoclingHealth } from "@/components/docling-health-banner";
import { ProtectedRoute } from "@/components/protected-route";
import { DotPattern } from "@/components/ui/dot-pattern";
import { cn } from "@/lib/utils";
import OnboardingCard from "./components/onboarding-card";

function OnboardingPage() {
  const { isHealthy: isDoclingHealthy } = useDoclingHealth();

  return (
    <div className="min-h-dvh w-full flex gap-5 flex-col items-center justify-center bg-background relative p-4">
      <DotPattern
        width={24}
        height={24}
        cx={1}
        cy={1}
        cr={1}
        className={cn(
          "[mask-image:linear-gradient(to_bottom,white,transparent,transparent)]",
          "text-input/70",
        )}
      />

      <DoclingHealthBanner className="absolute top-0 left-0 right-0 w-full z-20" />

      <div className="flex flex-col items-center gap-5 min-h-[550px] w-full z-10">
        <div className="flex flex-col items-center justify-center gap-4">
          <h1 className="text-2xl font-medium font-chivo">
            Connect a model provider
          </h1>
        </div>
        <OnboardingCard isDoclingHealthy={isDoclingHealthy} />
      </div>
    </div>
  );
}

export default function ProtectedOnboardingPage() {
  return (
    <ProtectedRoute>
      <Suspense fallback={<div>Loading onboarding...</div>}>
        <OnboardingPage />
      </Suspense>
    </ProtectedRoute>
  );
}
