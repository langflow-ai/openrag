"use client";

import { Search } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useGetModelCatalogQuery } from "@/app/api/queries/useGetModelsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import AnthropicLogo from "@/components/icons/anthropic-logo";
import IBMLogo from "@/components/icons/ibm-logo";
import OllamaLogo from "@/components/icons/ollama-logo";
import OpenAILogo from "@/components/icons/openai-logo";
import { useProviderHealth } from "@/components/provider-health-banner";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import {
  ALL_PROVIDERS,
  CLOUD_EXCLUDED_PROVIDERS,
  type ModelProvider,
} from "../_helpers/model-helpers";
import AnthropicSettingsDialog from "./anthropic-settings-dialog";
import CatalogProviderCard from "./catalog-provider-card";
import { GenericProviderDialog } from "./generic-provider-dialog";
import ModelProviderCard from "./model-provider-card";
import OllamaSettingsDialog from "./ollama-settings-dialog";
import OpenAISettingsDialog from "./openai-settings-dialog";
import WatsonxSettingsDialog from "./watsonx-settings-dialog";

// Providers with a bespoke settings dialog; they never appear in the
// catalogue section below.
const BUILT_IN_PROVIDERS = ["openai", "anthropic", "ollama", "watsonx"];

export const ModelProviders = () => {
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const searchParams = useSearchParams();
  const router = useRouter();
  const isCloudBrand = useIsCloudBrand();

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const { health } = useProviderHealth();

  const { data: catalog } = useGetModelCatalogQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const [dialogOpen, setDialogOpen] = useState<ModelProvider | undefined>();
  const [genericDialogOpen, setGenericDialogOpen] = useState(false);
  const [genericProvider, setGenericProvider] = useState<string>();
  const [search, setSearch] = useState("");

  const allProviderKeys = useMemo(() => {
    return isCloudBrand
      ? ALL_PROVIDERS.filter((p) => !CLOUD_EXCLUDED_PROVIDERS.includes(p))
      : ALL_PROVIDERS;
  }, [isCloudBrand]);

  const openGenericDialog = (providerKey: string) => {
    setGenericProvider(providerKey);
    setGenericDialogOpen(true);
  };

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

  // Custom (LiteLLM) providers the user has already set up. They keep their
  // place directly after the built-in cards, as before.
  const configuredCustomProviders = useMemo(
    () =>
      Object.entries(settings.providers?.custom ?? {})
        .filter(
          ([provider, value]) =>
            value.configured && !BUILT_IN_PROVIDERS.includes(provider),
        )
        .map(([provider]) => provider),
    [settings.providers?.custom],
  );

  // Everything else the installed LiteLLM version supports, listed below the
  // configured ones so the whole catalogue is browsable without a dropdown.
  const remainingProviders = useMemo(() => {
    const alreadyShown = new Set<string>([
      ...allProviderKeys,
      ...configuredCustomProviders,
    ]);
    return (catalog?.providers ?? []).filter(
      (entry) => !alreadyShown.has(entry.key),
    );
  }, [catalog?.providers, allProviderKeys, configuredCustomProviders]);

  const query = search.trim().toLowerCase();
  const matches = (key: string, name: string) =>
    query === "" ||
    key.toLowerCase().includes(query) ||
    name.toLowerCase().includes(query);

  const visibleProviderKeys = allProviderKeys.filter((key) =>
    matches(key, modelProvidersMap[key].name),
  );
  const visibleCustomProviders = configuredCustomProviders.filter((provider) =>
    matches(provider, provider),
  );
  const visibleRemainingProviders = remainingProviders.filter((entry) =>
    matches(entry.key, entry.name),
  );
  const hasResults =
    visibleProviderKeys.length > 0 ||
    visibleCustomProviders.length > 0 ||
    visibleRemainingProviders.length > 0;

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <p className="text-mmd text-muted-foreground">
          Configure any provider supported by LiteLLM.
        </p>
        <div className="relative w-full sm:w-72">
          <Search className="-translate-y-1/2 pointer-events-none absolute top-1/2 left-3 h-4 w-4 text-muted-foreground" />
          <Input
            aria-label="Search providers"
            className="pl-9"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search providers..."
            type="search"
            value={search}
          />
        </div>
      </div>
      <div className="grid gap-6 xs:grid-cols-1 md:grid-cols-2 lg:grid-cols-4">
        {visibleProviderKeys.map((providerKey) => {
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
        {visibleCustomProviders.map((provider) => (
          <CatalogProviderCard
            key={provider}
            providerKey={provider}
            name={provider}
            isConfigured
            onConfigure={openGenericDialog}
          />
        ))}
      </div>

      {visibleRemainingProviders.length > 0 && (
        <>
          <div className="mt-10 mb-6">
            <h3 className="font-medium">All providers</h3>
            <p className="text-mmd text-muted-foreground">
              Every provider supported by the installed LiteLLM version.
            </p>
          </div>
          <div className="grid gap-6 xs:grid-cols-1 md:grid-cols-2 lg:grid-cols-4">
            {visibleRemainingProviders.map((entry) => (
              <CatalogProviderCard
                key={entry.key}
                providerKey={entry.key}
                name={entry.name}
                isConfigured={false}
                onConfigure={openGenericDialog}
              />
            ))}
          </div>
        </>
      )}

      {!hasResults && (
        <p className="text-mmd text-muted-foreground">
          No providers match "{search}".
        </p>
      )}

      <GenericProviderDialog
        open={genericDialogOpen}
        onOpenChange={setGenericDialogOpen}
        initialProvider={genericProvider}
      />
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
