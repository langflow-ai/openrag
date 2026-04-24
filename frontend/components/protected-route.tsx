"use client";

import { Loader2 } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/contexts/auth-context";

interface ProtectedRouteProps {
  children: React.ReactNode;
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { isLoading, isAuthenticated, isNoAuthMode, isIbmAuthMode } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  console.log(
    "ProtectedRoute - isLoading:",
    isLoading,
    "isAuthenticated:",
    isAuthenticated,
    "isNoAuthMode:",
    isNoAuthMode,
    "isIbmAuthMode:",
    isIbmAuthMode,
    "pathname:",
    pathname,
  );

  useEffect(() => {
    if (isLoading) return;

    if (!isAuthenticated) {
      if (isNoAuthMode) return;
      if (isIbmAuthMode) {
        router.push("/unauthorized");
        return;
      }
      const redirectUrl = `/login?redirect=${encodeURIComponent(pathname)}`;
      router.push(redirectUrl);
    }
  }, [
    isLoading,
    isAuthenticated,
    isNoAuthMode,
    isIbmAuthMode,
    router,
    pathname,
  ]);

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

  if (isNoAuthMode) {
    return <>{children}</>;
  }

  if (!isAuthenticated) {
    return null;
  }

  return <>{children}</>;
}
