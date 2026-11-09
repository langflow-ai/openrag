"use client";

import { AlertTriangle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useProviderHealthQuery } from "@/app/api/queries/useProviderHealthQuery";
import { getProviderChrome } from "@/components/models/model-helpers";
import { Banner, BannerIcon, BannerTitle } from "@/components/ui/banner";
import { useChat } from "@/contexts/chat-context";
import { useNarrowLayout } from "@/hooks/use-narrow-layout";
import { cn } from "@/lib/utils";
import { Button } from "./ui/button";

interface ProviderHealthBannerProps {
  className?: string;
}

// Custom hook to check provider health status
export function useProviderHealth() {
  const { hasChatError } = useChat();
  const {
    data: health,
    isLoading,
    isFetching,
    error,
    isError,
  } = useProviderHealthQuery({
    // After a chat/ingest failure, probe completion so the banner shows the
    // real error (disabled key, missing model, etc.) — not only IAM auth.
    test_completion: hasChatError,
  });

  const isHealthy = health?.status === "healthy" && !isError;
  // Only consider unhealthy if backend is up but provider validation failed
  // Don't show banner if backend is unavailable
  const isUnhealthy =
    health?.status === "unhealthy" || health?.status === "error";
  const isBackendUnavailable =
    health?.status === "backend-unavailable" || isError;
  // Serving, but something outside provider setup needs attention. An
  // unhealthy verdict outranks it, so the two banners never compete.
  const isDegraded = isHealthy && (health?.warnings?.length ?? 0) > 0;

  return {
    health,
    isLoading,
    isFetching,
    error,
    isError,
    isHealthy,
    isUnhealthy,
    isDegraded,
    isBackendUnavailable,
  };
}

export function ProviderHealthBanner({ className }: ProviderHealthBannerProps) {
  const { isLoading, isHealthy, isUnhealthy, isDegraded, health } =
    useProviderHealth();
  const router = useRouter();
  const isNarrow = useNarrowLayout();

  // Only show banner when provider is unhealthy or degraded (not when the
  // backend is unavailable)
  if (isLoading || (isHealthy && !isDegraded)) {
    return null;
  }

  if (isDegraded) {
    // A warning, not an error: the provider is serving and its setup is fine.
    // The remedy (re-ingest or delete) lives on the Knowledge page, so that is
    // where the action goes rather than to provider settings.
    const [warning] = health?.warnings ?? [];
    const providerTitle = getProviderChrome(warning.provider).name;

    return (
      <Banner
        className={cn(
          "bg-amber-50 dark:bg-amber-950 text-foreground border-accent-amber border-b w-full",
          isNarrow && "flex-wrap gap-y-1 py-2",
          className,
        )}
      >
        <BannerIcon
          className="text-accent-amber-foreground shrink-0"
          icon={AlertTriangle}
        />
        <BannerTitle
          className={cn(
            "font-medium flex items-center gap-2",
            isNarrow && "text-xs",
          )}
        >
          {`${providerTitle} warning - ${warning.message}`}
        </BannerTitle>
        <Button
          size="sm"
          className="shrink-0"
          onClick={() => router.push("/knowledge")}
        >
          Open Knowledge
        </Button>
      </Banner>
    );
  }

  if (isUnhealthy) {
    const llmProvider = health?.llm_provider || health?.provider;
    const embeddingProvider = health?.embedding_provider;
    const llmError = health?.llm_error;
    const embeddingError = health?.embedding_error;

    // Determine which provider has the error
    let errorProvider: string | undefined;
    let errorMessage: string;

    // Prefer a single shared provider when LLM and embedding fail the same way
    // (e.g. both watsonx auth failures), so the banner stays readable.
    let showMultipleErrors = false;

    if (llmError && embeddingError) {
      if (llmError === embeddingError) {
        errorMessage = llmError;
        errorProvider =
          llmProvider === embeddingProvider ? llmProvider : undefined;
      } else {
        errorMessage = `${llmError}; ${embeddingError}`;
        errorProvider = undefined;
        showMultipleErrors = true;
      }
    } else if (llmError) {
      errorProvider = llmProvider;
      errorMessage = llmError;
    } else if (embeddingError) {
      errorProvider = embeddingProvider;
      errorMessage = embeddingError;
    } else {
      errorMessage = health?.message || "Provider validation failed";
      errorProvider = llmProvider;
    }

    // One label source for every provider, including ones added through
    // config/model_providers.yaml that have no built-in chrome.
    const providerTitle = errorProvider
      ? getProviderChrome(errorProvider).name
      : "Provider";

    const settingsUrl = errorProvider
      ? `/settings?setup=${errorProvider}`
      : "/settings";

    const bannerLabel = showMultipleErrors
      ? `Provider errors - ${errorMessage}`
      : `${providerTitle} error - ${errorMessage}`;

    return (
      <Banner
        className={cn(
          "bg-red-50 dark:bg-red-950 text-foreground border-accent-red border-b w-full",
          isNarrow && "flex-wrap gap-y-1 py-2",
          className,
        )}
      >
        <BannerIcon
          className="text-accent-red-foreground shrink-0"
          icon={AlertTriangle}
        />
        <BannerTitle
          className={cn(
            "font-medium flex items-center gap-2",
            isNarrow && "text-xs",
          )}
        >
          {bannerLabel}
        </BannerTitle>
        <Button
          size="sm"
          className="shrink-0"
          onClick={() => router.push(settingsUrl)}
        >
          Fix Setup
        </Button>
      </Banner>
    );
  }

  return null;
}
