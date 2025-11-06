import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ModelProvider } from "../helpers/model-helpers";
import OpenAILogo from "@/components/logo/openai-logo";
import IBMLogo from "@/components/logo/ibm-logo";
import OllamaLogo from "@/components/logo/ollama-logo";
import { useAuth } from "@/contexts/auth-context";
import { ReactNode, useState, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";

import OpenAISettingsDialog from "./openai-settings-dialog";
import OllamaSettingsDialog from "./ollama-settings-dialog";
import WatsonxSettingsDialog from "./watsonx-settings-dialog";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { useProviderHealth } from "@/components/provider-health-banner";

export const ModelProviders = () => {
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const searchParams = useSearchParams();
  const router = useRouter();

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const { isUnhealthy } = useProviderHealth();

  const [dialogOpen, setDialogOpen] = useState<ModelProvider | undefined>();

  const allProviderKeys: ModelProvider[] = ["openai", "ollama", "watsonx"];

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

  const currentProviderKey =
    (settings.provider?.model_provider as ModelProvider) || "openai";

  // Get all provider keys with active provider first
  const sortedProviderKeys = [
    currentProviderKey,
    ...allProviderKeys.filter((key) => key !== currentProviderKey),
  ];

  return (
    <>
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {sortedProviderKeys.map((providerKey) => {
          const {
            name,
            logo: Logo,
            logoColor,
            logoBgColor,
          } = modelProvidersMap[providerKey];
          const isCurrentProvider = providerKey === currentProviderKey;

          return (
            <Card
              key={providerKey}
              className={cn(
                "relative flex flex-col",
                !isCurrentProvider && "text-muted-foreground",
                isCurrentProvider && isUnhealthy && "border-destructive"
              )}
            >
              <CardHeader>
                <div className="flex flex-col items-start justify-between">
                  <div className="flex flex-col gap-3">
                    <div className="mb-1">
                      <div
                        className={cn(
                          "w-8 h-8 rounded flex items-center justify-center border",
                          isCurrentProvider ? logoBgColor : "bg-muted"
                        )}
                      >
                        {
                          <Logo
                            className={
                              isCurrentProvider
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
                        <div
                          className={cn(
                            "h-2 w-2 rounded-full",
                            isUnhealthy
                              ? "bg-destructive"
                              : "bg-accent-emerald-foreground"
                          )}
                        />
                      )}
                    </CardTitle>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col justify-end space-y-4">
                {isCurrentProvider ? (
                  <Button
                    variant={isUnhealthy ? "default" : "outline"}
                    onClick={() => setDialogOpen(providerKey)}
                  >
                    {isUnhealthy ? "Fix Setup" : "Edit Setup"}
                  </Button>
                ) : (
                  <p>
                    See{" "}
                    <Link
                      href="https://docs.openr.ag/install/#application-onboarding"
                      className="text-accent-purple-foreground"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Application onboarding docs
                    </Link>{" "}
                    for configuration detail.
                  </p>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
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
