"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import AnthropicLogo from "@/components/icons/anthropic-logo";
import AzureAIFoundryLogo from "@/components/icons/azure-ai-foundry-logo";
import IBMLogo from "@/components/icons/ibm-logo";
import OllamaLogo from "@/components/icons/ollama-logo";
import OpenAILogo from "@/components/icons/openai-logo";
import { useProviderHealth } from "@/components/provider-health-banner";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import {
  ALL_PROVIDERS,
  CLOUD_EXCLUDED_PROVIDERS,
  type ModelProvider,
} from "../_helpers/model-helpers";
import AnthropicSettingsDialog from "./anthropic-settings-dialog";
import AzureAIFoundrySettingsDialog from "./azure-ai-foundry-settings-dialog";
import ModelProviderCard from "./model-provider-card";
import OllamaSettingsDialog from "./ollama-settings-dialog";
import OpenAISettingsDialog from "./openai-settings-dialog";
import WatsonxSettingsDialog from "./watsonx-settings-dialog";

export const ModelProviders = () => {
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const searchParams = useSearchParams();
  const router = useRouter();
  const isCloudBrand = useIsCloudBrand();

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const { health } = useProviderHealth();

  const [dialogOpen, setDialogOpen] = useState<ModelProvider | undefined>();

  const showAzureAiProviders = settings.show_azure_ai_providers === true;

  const allProviderKeys = useMemo(() => {
    const excluded = isCloudBrand ? CLOUD_EXCLUDED_PROVIDERS : [];
    return ALL_PROVIDERS.filter((p) => {
      if (excluded.includes(p)) return false;
      if (!showAzureAiProviders && p === "azure_ai_foundry") {
        return false;
      }
      return true;
    });
  }, [isCloudBrand, showAzureAiProviders]);

  // Handle URL search param to open dialogs
  useEffect(() => {
    const searchParam = searchParams.get("setup");
    if (searchParam && allProviderKeys.includes(searchParam as ModelProvider)) {
      setDialogOpen(searchParam as ModelProvider);
    }
  }, [searchParams, allProviderKeys]);

  // Function to close dialog and remove search param
  const handleCloseDialog = () => {
    setDialogOpen(undefined);
    // Remove search param from URL
    const params = new URLSearchParams(searchParams.toString());
    params.delete("setup");
    const newUrl = params.toString()
      ? `${window.location.pathname}?${params.toString()}`
      : window.location.pathname;
    router.replace(newUrl);
  };

  const modelProvidersMap: Record<
    ModelProvider,
    {
      name: string;
      logo: (props: React.SVGProps<SVGSVGElement>) => ReactNode;
      logoColor: string;
      logoBgColor: string;
    }
  > = {
    openai: {
      name: "OpenAI",
      logo: OpenAILogo,
      logoColor: "text-black",
      logoBgColor: "bg-white",
    },
    anthropic: {
      name: "Anthropic",
      logo: AnthropicLogo,
      logoColor: "text-[#D97757]",
      logoBgColor: "bg-white",
    },
    ollama: {
      name: "Ollama",
      logo: OllamaLogo,
      logoColor: "text-black",
      logoBgColor: "bg-white",
    },
    watsonx: {
      name: "IBM watsonx.ai",
      logo: IBMLogo,
      logoColor: "text-white",
      logoBgColor: "bg-[#1063FE]",
    },
    azure_ai_foundry: {
      name: "Azure AI Foundry",
      logo: AzureAIFoundryLogo,
      logoColor: "text-white",
      logoBgColor: "bg-[#0078D4]",
    },
    local: {
      name: "Local",
      logo: (props) => (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          {...props}
        >
          <rect x="4" y="4" width="16" height="16" rx="2" />
          <rect x="9" y="9" width="6" height="6" />
          <path d="M9 1v3" />
          <path d="M15 1v3" />
          <path d="M9 20v3" />
          <path d="M15 20v3" />
          <path d="M20 9h3" />
          <path d="M20 15h3" />
          <path d="M1 9h3" />
          <path d="M1 15h3" />
        </svg>
      ),
      logoColor: "text-muted-foreground",
      logoBgColor: "bg-white",
    },
  };

  const currentLlmProvider =
    (settings.agent?.llm_provider as ModelProvider) || "openai";
  const currentEmbeddingProvider =
    (settings.knowledge?.embedding_provider as ModelProvider) || "openai";

  return (
    <>
      <div className="grid gap-6 xs:grid-cols-1 md:grid-cols-2 lg:grid-cols-4">
        {allProviderKeys.map((providerKey) => {
          const isLlmProvider = providerKey === currentLlmProvider;
          const isEmbeddingProvider = providerKey === currentEmbeddingProvider;
          const isProviderUnhealthy =
            (isLlmProvider && health?.llm_error) ||
            (isEmbeddingProvider && health?.embedding_error);

          return (
            <ModelProviderCard
              key={providerKey}
              provider={{ providerKey, ...modelProvidersMap[providerKey] }}
              isConfigured={!!settings.providers?.[providerKey]?.configured}
              isUnhealthy={!!isProviderUnhealthy}
              onConfigure={setDialogOpen}
            />
          );
        })}
      </div>
      <AnthropicSettingsDialog
        open={dialogOpen === "anthropic"}
        setOpen={handleCloseDialog}
      />
      <OpenAISettingsDialog
        open={dialogOpen === "openai"}
        setOpen={handleCloseDialog}
      />
      <OllamaSettingsDialog
        open={dialogOpen === "ollama"}
        setOpen={handleCloseDialog}
      />
      <WatsonxSettingsDialog
        open={dialogOpen === "watsonx"}
        setOpen={handleCloseDialog}
      />
      <AzureAIFoundrySettingsDialog
        open={dialogOpen === "azure_ai_foundry"}
        setOpen={handleCloseDialog}
      />
    </>
  );
};

export default ModelProviders;
