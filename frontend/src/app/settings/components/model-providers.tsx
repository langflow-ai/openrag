import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ModelProvider } from "../helpers/model-helpers";
import OpenAILogo from "@/components/logo/openai-logo";
import IBMLogo from "@/components/logo/ibm-logo";
import OllamaLogo from "@/components/logo/ollama-logo";
import { useAuth } from "@/contexts/auth-context";
import { ReactNode, useState } from "react";

import OpenAISettingsDialog from "./openai-settings-dialog";
import OllamaSettingsDialog from "./ollama-settings-dialog";
import WatsonxSettingsDialog from "./watsonx-settings-dialog";
import { cn } from "@/lib/utils";
import Link from "next/link";

export const ModelProviders = () => {
  const { isAuthenticated, isNoAuthMode } = useAuth();

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const [dialogOpen, setDialogOpen] = useState<ModelProvider | undefined>();

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
  const allProviderKeys: ModelProvider[] = ["openai", "ollama", "watsonx"];
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
          const isActive = providerKey === currentProviderKey;

          return (
            <Card
              key={providerKey}
              className={cn(
                "relative flex flex-col",
                !isActive && "text-muted-foreground"
              )}
            >
              <CardHeader>
                <div className="flex flex-col items-start justify-between">
                  <div className="flex flex-col gap-3">
                    <div className="mb-1">
                      <div
                        className={cn(
                          "w-8 h-8 rounded flex items-center justify-center border",
                          isActive ? logoBgColor : "bg-muted"
                        )}
                      >
                        {
                          <Logo
                            className={
                              isActive ? logoColor : "text-muted-foreground"
                            }
                          />
                        }
                      </div>
                    </div>
                    <CardTitle className="flex flex-row items-center gap-2">
                      {name}
                      {isActive && (
                        <div className="h-2 w-2 bg-accent-emerald-foreground rounded-full" />
                      )}
                    </CardTitle>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col justify-end space-y-4">
                {isActive ? (
                  <Button
                    variant="outline"
                    onClick={() => setDialogOpen(providerKey)}
                  >
                    Edit Setup
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
        setOpen={() => setDialogOpen(undefined)}
      />
      <OllamaSettingsDialog
        open={dialogOpen === "ollama"}
        setOpen={() => setDialogOpen(undefined)}
      />
      <WatsonxSettingsDialog
        open={dialogOpen === "watsonx"}
        setOpen={() => setDialogOpen(undefined)}
      />
    </>
  );
};

export default ModelProviders;
