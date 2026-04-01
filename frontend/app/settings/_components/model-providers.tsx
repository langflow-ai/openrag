import { useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import AnthropicLogo from "@/components/icons/anthropic-logo";
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

  const allProviderKeys = isCloudBrand
    ? ALL_PROVIDERS.filter((p) => !CLOUD_EXCLUDED_PROVIDERS.includes(p))
    : ALL_PROVIDERS;

  // Handle URL search param to open dialogs
  useEffect(() => {
    const searchParam = searchParams.get("setup");
    if (searchParam && allProviderKeys.includes(searchParam as ModelProvider)) {
      setDialogOpen(searchParam as ModelProvider);
    }
  }, [searchParams]);

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
    </>
  );
};

export default ModelProviders;
