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
  const isUnhealthy =
    health?.status === "unhealthy" || health?.status === "error" || isError;

  return {
    health,
    isLoading,
    isFetching,
    error,
    isError,
    isHealthy,
    isUnhealthy,
  };
}

export function ProviderHealthBanner({ className }: ProviderHealthBannerProps) {
  const { isLoading, isHealthy, error } = useProviderHealth();
  const router = useRouter();

  const { data: settings = {} } = useGetSettingsQuery();

  if (!isHealthy && !isLoading) {
    const errorMessage = error?.message || "Provider validation failed";
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
