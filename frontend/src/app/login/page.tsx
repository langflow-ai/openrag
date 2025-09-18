"use client";

import { Loader2, Lock, LogIn } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuth } from "@/contexts/auth-context";
import { useGetSettingsQuery } from "../api/queries/useGetSettingsQuery";

function LoginPageContent() {
  const { isLoading, isAuthenticated, isNoAuthMode, login } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  const { data: settings } = useGetSettingsQuery({
    enabled: isAuthenticated,
  });

  const redirect =
    settings && !settings.edited
      ? "/onboarding"
      : searchParams.get("redirect") || "/chat";

  // Redirect if already authenticated or in no-auth mode
  useEffect(() => {
    if (!isLoading && (isAuthenticated || isNoAuthMode)) {
      router.push(redirect);
    }
  }, [isLoading, isAuthenticated, isNoAuthMode, router, redirect]);

  if (isLoading) {
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
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center space-y-4">
          <div className="flex items-center justify-center w-16 h-16 bg-primary/10 rounded-full mx-auto">
            <Lock className="h-8 w-8 text-primary" />
          </div>
          <div>
            <CardTitle className="text-2xl">Welcome to OpenRAG</CardTitle>
            <CardDescription className="mt-2">
              Sign in to access your documents and AI chat
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          <Button onClick={login} className="w-full" size="lg">
            <LogIn className="h-4 w-4 mr-2" />
            Sign In with Google
          </Button>

          <p className="text-xs text-center text-muted-foreground">
            By signing in, you agree to our terms of service and privacy policy.
          </p>
        </CardContent>
      </Card>
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
