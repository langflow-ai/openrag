import { useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import AnthropicLogo from "@/components/logo/anthropic-logo";
import IBMLogo from "@/components/logo/ibm-logo";
import OllamaLogo from "@/components/logo/ollama-logo";
import OpenAILogo from "@/components/logo/openai-logo";
import { useProviderHealth } from "@/components/provider-health-banner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/contexts/auth-context";
import { cn } from "@/lib/utils";
import type { ModelProvider } from "../helpers/model-helpers";
import AnthropicSettingsDialog from "./anthropic-settings-dialog";
import OllamaSettingsDialog from "./ollama-settings-dialog";
import OpenAISettingsDialog from "./openai-settings-dialog";
import WatsonxSettingsDialog from "./watsonx-settings-dialog";

export const ModelProviders = () => {
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const searchParams = useSearchParams();
  const router = useRouter();

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const { health } = useProviderHealth();

  const [dialogOpen, setDialogOpen] = useState<ModelProvider | undefined>();

  const allProviderKeys: ModelProvider[] = [
    "openai",
    "ollama",
    "watsonx",
    "anthropic",
  ];

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

  // Get all provider keys with active providers first
  const activeProviders = new Set([
    currentLlmProvider,
    currentEmbeddingProvider,
  ]);
  const sortedProviderKeys = [
    ...Array.from(activeProviders),
    ...allProviderKeys.filter((key) => !activeProviders.has(key)),
  ];

  return (
    <>
      <div className="grid gap-6 xs:grid-cols-1 md:grid-cols-2 lg:grid-cols-4">
        {sortedProviderKeys.map((providerKey) => {
          const {
            name,
            logo: Logo,
            logoColor,
            logoBgColor,
          } = modelProvidersMap[providerKey];
          const isLlmProvider = providerKey === currentLlmProvider;
          const isEmbeddingProvider = providerKey === currentEmbeddingProvider;
          const isCurrentProvider = isLlmProvider || isEmbeddingProvider;

          // Check if this specific provider is unhealthy
          const hasLlmError = isLlmProvider && health?.llm_error;
          const hasEmbeddingError =
            isEmbeddingProvider && health?.embedding_error;
          const isProviderUnhealthy = hasLlmError || hasEmbeddingError;

          return (
            <Card
              key={providerKey}
              className={cn(
                "relative flex flex-col",
                !settings.providers?.[providerKey]?.configured &&
                  "text-muted-foreground",
                isProviderUnhealthy && "border-destructive",
              )}
            >
              <CardHeader>
                <div className="flex flex-col items-start justify-between">
                  <div className="flex flex-col gap-3">
                    <div className="mb-1">
                      <div
                        className={cn(
                          "w-8 h-8 rounded flex items-center justify-center border",
                          settings.providers?.[providerKey]?.configured
                            ? logoBgColor
                            : "bg-muted",
                        )}
                      >
                        {
                          <Logo
                            className={
                              settings.providers?.[providerKey]?.configured
                                ? logoColor
                                : "text-muted-foreground"
                            }
                          />
                        }
                      </div>
                    </div>
                    <CardTitle className="flex flex-row items-center gap-2">
                      {name}
                      {isCurrentProvider && (
                        <span
                          className={cn(
                            "h-2 w-2 rounded-full",
                            isProviderUnhealthy
                              ? "bg-destructive"
                              : "bg-accent-emerald-foreground",
                          )}
                          aria-label={isProviderUnhealthy ? "Error" : "Active"}
                        />
                      )}
                    </CardTitle>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col justify-end space-y-4">
                <Button
                  variant={isProviderUnhealthy ? "default" : "outline"}
                  onClick={() => setDialogOpen(providerKey)}
                >
                  {isProviderUnhealthy
                    ? "Fix Setup"
                    : settings.providers?.[providerKey]?.configured
                      ? "Edit Setup"
                      : "Configure"}
                </Button>
              </CardContent>
            </Card>
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
