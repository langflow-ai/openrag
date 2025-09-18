"use client";

import { Suspense } from "react";
import { useUpdateFlowSettingMutation } from "@/app/api/mutations/useUpdateFlowSettingMutation";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { ProtectedRoute } from "@/components/protected-route";
import { useAuth } from "@/contexts/auth-context";

function OnboardingPage() {
  const { isAuthenticated } = useAuth();
  // Fetch settings using React Query
  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated,
  });

  // Mutations
  const updateFlowSettingMutation = useUpdateFlowSettingMutation({
    onSuccess: () => {
      console.log("Setting updated successfully");
    },
    onError: (error) => {
      console.error("Failed to update setting:", error.message);
    },
  });

  return <div className="space-y-8">Hello!</div>;
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
