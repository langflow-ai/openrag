"use client";

import Logo from "@/components/icons/openrag-logo";

/**
 * Shown to non-admin users when the workspace has not been onboarded yet.
 *
 * Onboarding is admin-only (the backend gates it behind `config:write`), so
 * non-admins can't run the wizard. Instead of the onboarding flow, they see
 * this "contact your administrator" screen. It renders inside the same card
 * shell as the onboarding wizard (see `chat-renderer.tsx`), so it inherits the
 * wizard's container sizing and entrance animation — this component only needs
 * to fill that card and center its content.
 */
export function OnboardingBlocked() {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-6 px-8 text-center">
      <Logo className="fill-primary" width={50} height={40} />
      <h1 className="text-2xl font-medium font-chivo">
        OpenRAG isn&apos;t set up yet
      </h1>
      <p className="max-w-md text-muted-foreground">
        An admin needs to finish setting up OpenRAG for this workspace before it
        can be used. Once that&apos;s done, check back here.
      </p>
      <button
        onClick={() => window.location.reload()}
        className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
      >
        Refresh
      </button>
    </div>
  );
}
