"use client";

import { Clock } from "lucide-react";
import Logo from "@/components/icons/openrag-logo";

/**
 * Shown to non-admin users when the workspace has not been onboarded yet.
 *
 * Onboarding is admin-only (the backend gates it behind `config:write`), so
 * non-admins can't run the wizard. Instead of the onboarding flow, they see
 * this "contact your administrator" screen. Mirrors the structure/classes of
 * `app/unauthorized/page.tsx` to stay on-brand.
 */
export function OnboardingBlocked() {
  return (
    <div className="min-h-dvh relative flex gap-4 flex-col items-center justify-center bg-card rounded-lg m-4">
      <div className="flex flex-col items-center justify-center gap-6 z-10 max-w-md px-4 text-center">
        <Logo className="fill-primary" width={50} height={40} />
        <Clock className="h-12 w-12 text-muted-foreground" />
        <h1 className="text-2xl font-medium font-chivo">
          OpenRAG isn&apos;t set up yet
        </h1>
        <p className="text-muted-foreground">
          Your workspace hasn&apos;t been onboarded. Please contact your
          administrator to finish setting up OpenRAG, then refresh this page.
        </p>
        <button
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
        >
          Refresh
        </button>
      </div>
    </div>
  );
}
