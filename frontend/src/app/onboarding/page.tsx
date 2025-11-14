"use client";

import { Suspense, useEffect } from "react";
import { useRouter } from "next/navigation";
import { DoclingHealthBanner } from "@/components/docling-health-banner";
import { ProtectedRoute } from "@/components/protected-route";
import { DotPattern } from "@/components/ui/dot-pattern";
import { cn } from "@/lib/utils";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import OnboardingCard from "./components/onboarding-card";

function LegacyOnboardingPage() {
  const router = useRouter();
  const { data: settingsDb, isLoading: isSettingsLoading } =
    useGetSettingsQuery();

  // Redirect if already completed onboarding
  useEffect(() => {
    if (!isSettingsLoading && settingsDb && settingsDb.edited) {
      router.push("/");
    }
  }, [isSettingsLoading, settingsDb, router]);

  const handleComplete = () => {
    router.push("/");
  };

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
        <OnboardingCard onComplete={handleComplete} />
      </div>
    </div>
  );
}

function OnboardingRouter() {
  const updatedOnboarding = process.env.UPDATED_ONBOARDING === "true";
  const router = useRouter();

  useEffect(() => {
    if (updatedOnboarding) {
      router.push("/new-onboarding");
    }
  }, [updatedOnboarding, router]);

  if (updatedOnboarding) {
    return null;
  }

  return <LegacyOnboardingPage />;
}

export default function ProtectedOnboardingPage() {
  return (
    <ProtectedRoute>
      <Suspense fallback={<div>Loading onboarding...</div>}>
        <OnboardingRouter />
      </Suspense>
    </ProtectedRoute>
  );
}
