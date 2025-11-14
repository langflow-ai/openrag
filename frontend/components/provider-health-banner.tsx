"use client";

import { AlertTriangle } from "lucide-react";
import { useRouter } from "next/navigation";
import type { ModelProvider } from "@/app/settings/helpers/model-helpers";
import { Banner, BannerIcon, BannerTitle } from "@/components/ui/banner";
import { cn } from "@/lib/utils";
import { useProviderHealthQuery } from "@/src/app/api/queries/useProviderHealthQuery";
import { Button } from "./ui/button";

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

const providerTitleMap: Record<ModelProvider, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  ollama: "Ollama",
  watsonx: "IBM watsonx.ai",
};

export function ProviderHealthBanner({ className }: ProviderHealthBannerProps) {
  const { isLoading, isHealthy, isUnhealthy, health } = useProviderHealth();
  const router = useRouter();

  // Only show banner when provider is unhealthy (not when backend is unavailable)
  if (isLoading || isHealthy) {
    return null;
  }

  if (isUnhealthy) {
    const llmProvider = health?.llm_provider || health?.provider;
    const embeddingProvider = health?.embedding_provider;
    const llmError = health?.llm_error;
    const embeddingError = health?.embedding_error;

    // Determine which provider has the error
    let errorProvider: string | undefined;
    let errorMessage: string;

    if (llmError && embeddingError) {
      // Both have errors - show combined message
      errorMessage = health?.message || "Provider validation failed";
      errorProvider = undefined; // Don't link to a specific provider
    } else if (llmError) {
      // Only LLM has error
      errorProvider = llmProvider;
      errorMessage = llmError;
    } else if (embeddingError) {
      // Only embedding has error
      errorProvider = embeddingProvider;
      errorMessage = embeddingError;
    } else {
      // Fallback to original message
      errorMessage = health?.message || "Provider validation failed";
      errorProvider = llmProvider;
    }

    const providerTitle = errorProvider
      ? providerTitleMap[errorProvider as ModelProvider] || errorProvider
      : "Provider";

    const settingsUrl = errorProvider
      ? `/settings?setup=${errorProvider}`
      : "/settings";

    return (
      <Banner
        className={cn(
          "bg-red-50 dark:bg-red-950 text-foreground border-accent-red border-b w-full",
          className,
        )}
      >
        <BannerIcon
          className="text-accent-red-foreground"
          icon={AlertTriangle}
        />
        <BannerTitle className="font-medium flex items-center gap-2">
          {llmError && embeddingError ? (
            <>Provider errors - {errorMessage}</>
          ) : (
            <>
              {providerTitle} error - {errorMessage}
            </>
          )}
        </BannerTitle>
        <Button size="sm" onClick={() => router.push(settingsUrl)}>
          Fix Setup
        </Button>
      </Banner>
    );
  }

  return null;
}
