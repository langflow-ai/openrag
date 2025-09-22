"use client";

import { Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import GoogleLogo from "@/components/logo/google-logo";
import Logo from "@/components/logo/logo";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/auth-context";
import { useGetSettingsQuery } from "../api/queries/useGetSettingsQuery";

function LoginPageContent() {
  const { isLoading, isAuthenticated, isNoAuthMode, login } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  const { data: settings, isLoading: isSettingsLoading } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const redirect =
    settings && !settings.edited
      ? "/onboarding"
      : searchParams.get("redirect") || "/chat";

  // Redirect if already authenticated or in no-auth mode
  useEffect(() => {
    if (!isLoading && !isSettingsLoading && (isAuthenticated || isNoAuthMode)) {
      router.push(redirect);
    }
  }, [
    isLoading,
    isSettingsLoading,
    isAuthenticated,
    isNoAuthMode,
    router,
    redirect,
  ]);

  if (isLoading || isSettingsLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin" />
          <p className="text-muted-foreground">Loading...</p>
        </div>
      </div>
    );
  }

  if (isAuthenticated || isNoAuthMode) {
    return null; // Will redirect in useEffect
  }

  return (
    <div
      className="min-h-dvh relative flex gap-4 flex-col items-center justify-center bg-background p-4"
      style={{
        backgroundImage: "url('/images/background.png')",
        backgroundSize: "cover",
        backgroundPosition: "center",
      }}
    >
      <div className="flex flex-col items-center justify-center gap-4">
        <Logo className="fill-primary" width={32} height={28} />
        <h1 className="text-2xl font-medium font-chivo">Welcome to OpenRAG</h1>
        <p className="text-sm text-muted-foreground">
          All your knowledge at your fingertips.
        </p>
        <Button onClick={login} className="w-80 gap-1.5" size="lg">
          <GoogleLogo className="h-4 w-4" />
          Continue with Google
        </Button>
      </div>
      <div className="flex items-center justify-center gap-2 absolute bottom-6 text-xs text-muted-foreground">
        <p className="text-accent-emerald-foreground">Systems Operational</p>•
        <p>Privacy Policy</p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-background">
          <div className="flex flex-col items-center gap-4">
            <Loader2 className="h-8 w-8 animate-spin" />
            <p className="text-muted-foreground">Loading...</p>
          </div>
        </div>
      }
    >
      <LoginPageContent />
    </Suspense>
  );
}
