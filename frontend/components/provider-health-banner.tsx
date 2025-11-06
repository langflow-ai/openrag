"use client";

import { AlertTriangle } from "lucide-react";
import { Banner, BannerIcon, BannerTitle } from "@/components/ui/banner";
import { cn } from "@/lib/utils";
import { useProviderHealthQuery } from "@/src/app/api/queries/useProviderHealthQuery";
import { Button } from "./ui/button";
import { useRouter } from "next/navigation";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";

interface ProviderHealthBannerProps {
  className?: string;
}

// Custom hook to check provider health status
export function useProviderHealth() {
  const {
    data: health,
    isLoading,
    isFetching,
    error,
    isError,
  } = useProviderHealthQuery();

  const isHealthy = health?.status === "healthy" && !isError;
  // Only consider unhealthy if backend is up but provider validation failed
  // Don't show banner if backend is unavailable
  const isUnhealthy =
    health?.status === "unhealthy" || health?.status === "error";
  const isBackendUnavailable =
    health?.status === "backend-unavailable" || isError;

  return {
    health,
    isLoading,
    isFetching,
    error,
    isError,
    isHealthy,
    isUnhealthy,
    isBackendUnavailable,
  };
}

export function ProviderHealthBanner({ className }: ProviderHealthBannerProps) {
  const { isLoading, isHealthy, isUnhealthy, health } = useProviderHealth();
  const router = useRouter();

  const { data: settings = {} } = useGetSettingsQuery();

  // Only show banner when provider is unhealthy (not when backend is unavailable)
  if (isLoading || isHealthy) {
    return null;
  }

  if (isUnhealthy) {
    const errorMessage = health?.message || "Provider validation failed";
    const settingsUrl = settings.provider?.model_provider
      ? `/settings?setup=${settings.provider?.model_provider}`
      : "/settings";

    return (
      <Banner
        className={cn(
          "bg-red-50 dark:bg-red-950 text-foreground border-accent-red border-b w-full",
          className
        )}
      >
        <BannerIcon
          className="text-accent-red-foreground"
          icon={AlertTriangle}
        />
        <BannerTitle className="font-medium flex items-center gap-2">
          {errorMessage}
        </BannerTitle>
        <Button size="sm" onClick={() => router.push(settingsUrl)}>
          Fix Setup
        </Button>
      </Banner>
    );
  }

  return null;
}
