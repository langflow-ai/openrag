"use client";

import { Loader2, ShieldAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import Logo from "@/components/icons/openrag-logo";
import { useAuth } from "@/contexts/auth-context";

export default function UnauthorizedPage() {
  const { isLoading, isAuthenticated, isIbmAuthMode } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.push("/chat");
    }
  }, [isLoading, isAuthenticated, router]);

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

  if (isAuthenticated) {
    return null;
  }

  return (
    <div className="min-h-dvh relative flex gap-4 flex-col items-center justify-center bg-card rounded-lg m-4">
      <div className="flex flex-col items-center justify-center gap-6 z-10 max-w-md px-4 text-center">
        <Logo className="fill-primary" width={50} height={40} />
        <ShieldAlert className="h-12 w-12 text-destructive" />
        <h1 className="text-2xl font-medium font-chivo">
          Authentication Required
        </h1>
        {isIbmAuthMode ? (
          <p className="text-muted-foreground">
            Your session could not be authenticated. Please ensure you are
            accessing OpenRAG through IBM watsonx.data with valid credentials.
          </p>
        ) : (
          <p className="text-muted-foreground">
            You do not have permission to access this page. Please sign in to
            continue.
          </p>
        )}
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
        >
          Retry
        </button>
      </div>
    </div>
  );
}
