"use client";

import { AlertTriangle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useProviderHealthQuery } from "@/app/api/queries/useProviderHealthQuery";
import type { ModelProvider } from "@/app/settings/_helpers/model-helpers";
import { Banner, BannerIcon, BannerTitle } from "@/components/ui/banner";
import { useChat } from "@/contexts/chat-context";
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
    test_completion: hasChatError, // Use test_completion=true when chat errors occur
  });

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

    const providerTitle = errorProvider
      ? providerTitleMap[errorProvider as ModelProvider] || errorProvider
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
          className,
        )}
      >
        <BannerIcon
          className="text-accent-red-foreground"
          icon={AlertTriangle}
        />
        <BannerTitle className="font-medium flex items-center gap-2">
          {bannerLabel}
        </BannerTitle>
        <Button size="sm" onClick={() => router.push(settingsUrl)}>
          Fix Setup
        </Button>
      </Banner>
    );
  }

  return null;
}
