"use client";

import { Loader2 } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/contexts/auth-context";

interface ProtectedRouteProps {
  children: React.ReactNode;
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { isLoading, isAuthenticated, isNoAuthMode } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  console.log(
    "ProtectedRoute - isLoading:",
    isLoading,
    "isAuthenticated:",
    isAuthenticated,
    "isNoAuthMode:",
    isNoAuthMode,
    "pathname:",
    pathname,
  );

  useEffect(() => {
    if (!isLoading && !isAuthenticated && !isNoAuthMode) {
      // Redirect to login with current path as redirect parameter
      const redirectUrl = `/login?redirect=${encodeURIComponent(pathname)}`;
      router.push(redirectUrl);
      return;
    }
  }, [isLoading, isAuthenticated, isNoAuthMode, router, pathname]);

  // Show loading state while checking authentication
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin" />
          <p className="text-muted-foreground">Loading...</p>
        </div>
      </div>
    );
  }

  // In no-auth mode, always render content
  if (isNoAuthMode) {
    return <>{children}</>;
  }

  // Don't render anything if not authenticated (will redirect)
  if (!isAuthenticated) {
    return null;
  }

  // Render protected content
  return <>{children}</>;
}
