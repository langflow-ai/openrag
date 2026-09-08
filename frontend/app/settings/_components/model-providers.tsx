"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useGetModelProvidersQuery } from "@/app/api/queries/useGetModelProvidersQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { useProviderHealth } from "@/components/provider-health-banner";
import { useAuth } from "@/contexts/auth-context";
import {
  getProviderChrome,
  type ModelProvider,
} from "../_helpers/model-helpers";
import AnthropicSettingsDialog from "./anthropic-settings-dialog";
import ModelProviderCard from "./model-provider-card";
import OllamaSettingsDialog from "./ollama-settings-dialog";
import OpenAISettingsDialog from "./openai-settings-dialog";
import ProviderSettingsDialog from "./provider-settings-dialog";
import WatsonxSettingsDialog from "./watsonx-settings-dialog";

// Providers with a hand-built credential dialog. Everything else the backend
// offers is configured through the catalogue-driven ProviderSettingsDialog.
const BESPOKE_DIALOG_PROVIDERS = new Set<ModelProvider>([
  "openai",
  "anthropic",
  "ollama",
  "watsonx",
]);

export const ModelProviders = () => {
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const searchParams = useSearchParams();
  const router = useRouter();

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  // The backend filters this list by OPENRAG_RUN_MODE (see
  // config/model_providers.yaml). The UI keeps no denylist of its own, and the
  // IBM theme no longer decides what is available.
  const {
    data: providerData,
    isLoading: isLoadingProviders,
    isError: providersFailed,
  } = useGetModelProvidersQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const { health } = useProviderHealth();

  const [dialogOpen, setDialogOpen] = useState<ModelProvider | undefined>();

  const providers = useMemo(
    () => providerData?.providers ?? [],
    [providerData],
  );
  const allProviderKeys = useMemo(
    () => providers.map((provider) => provider.name),
    [providers],
  );

  // Handle URL search param to open dialogs
  useEffect(() => {
    const searchParam = searchParams.get("setup");
    if (searchParam && allProviderKeys.includes(searchParam)) {
      setDialogOpen(searchParam);
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

  const currentLlmProvider =
    (settings.agent?.llm_provider as ModelProvider) || "openai";
  const currentEmbeddingProvider =
    (settings.knowledge?.embedding_provider as ModelProvider) || "openai";

  const genericDialogProvider =
    dialogOpen && !BESPOKE_DIALOG_PROVIDERS.has(dialogOpen)
      ? dialogOpen
      : undefined;

  if (providersFailed) {
    return (
      <p className="text-sm text-destructive">
        The list of model providers could not be loaded. Refresh to try again.
      </p>
    );
  }

  return (
    <>
      <div className="grid gap-6 xs:grid-cols-1 md:grid-cols-2 lg:grid-cols-4">
        {providers.map(({ name: providerKey, display_name }) => {
          const isLlmProvider = providerKey === currentLlmProvider;
          const isEmbeddingProvider = providerKey === currentEmbeddingProvider;
          const isProviderUnhealthy =
            (isLlmProvider && health?.llm_error) ||
            (isEmbeddingProvider && health?.embedding_error);

          return (
            <ModelProviderCard
              key={providerKey}
              provider={{
                providerKey,
                ...getProviderChrome(providerKey, display_name),
              }}
              // `providers.custom` carries every provider the backend knows,
              // legacy four included, so one lookup covers config-added ones.
              isConfigured={
                settings.providers?.custom?.[providerKey]?.configured === true
              }
              isUnhealthy={!!isProviderUnhealthy}
              onConfigure={setDialogOpen}
            />
          );
        })}
      </div>
      {!isLoadingProviders && providers.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No model providers are enabled for this deployment.
        </p>
      )}
      {allProviderKeys.includes("anthropic") && (
        <AnthropicSettingsDialog
          open={dialogOpen === "anthropic"}
          setOpen={handleCloseDialog}
        />
      )}
      {allProviderKeys.includes("openai") && (
        <OpenAISettingsDialog
          open={dialogOpen === "openai"}
          setOpen={handleCloseDialog}
        />
      )}
      {allProviderKeys.includes("ollama") && (
        <OllamaSettingsDialog
          open={dialogOpen === "ollama"}
          setOpen={handleCloseDialog}
        />
      )}
      {allProviderKeys.includes("watsonx") && (
        <WatsonxSettingsDialog
          open={dialogOpen === "watsonx"}
          setOpen={handleCloseDialog}
        />
      )}
      {genericDialogProvider && (
        <ProviderSettingsDialog
          provider={genericDialogProvider}
          displayName={
            providers.find(
              (provider) => provider.name === genericDialogProvider,
            )?.display_name
          }
          open
          setOpen={handleCloseDialog}
        />
      )}
    </>
  );
};

export default ModelProviders;
