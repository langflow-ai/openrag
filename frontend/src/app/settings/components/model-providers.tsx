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

export const ModelProviders = () => {
  const { isAuthenticated, isNoAuthMode } = useAuth();

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const [dialogOpen, setDialogOpen] = useState(false);

  const modelProvidersMap: Record<
    ModelProvider,
    { name: string; logo: ReactNode }
  > = {
    openai: {
      name: "OpenAI",
      logo: <OpenAILogo />,
    },
    ollama: {
      name: "Ollama",
      logo: <OllamaLogo />,
    },
    watsonx: {
      name: "IBM watsonx.ai",
      logo: <IBMLogo />,
    },
  };

  const currentProvider = modelProvidersMap[
    (settings.provider?.model_provider as ModelProvider) || "openai"
  ] as { name: string; logo: ReactNode };

  return (
    <>
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        <Card className="relative flex flex-col">
          <CardHeader>
            <div className="flex flex-col items-start justify-between">
              <div className="flex flex-col gap-3">
                <div className="mb-1">
                  <div className="w-8 h-8 rounded flex items-center justify-center">
                    {currentProvider.logo}
                  </div>
                </div>
                <CardTitle className="flex flex-row items-center gap-2">
                  {currentProvider.name}
                  <div className="h-2 w-2 bg-accent-emerald rounded-full" />
                </CardTitle>
              </div>
            </div>
          </CardHeader>
          <CardContent className="flex-1 flex flex-col justify-end space-y-4">
            <Button onClick={() => setDialogOpen(true)}>Edit Setup</Button>
          </CardContent>
        </Card>
      </div>
    <OpenAISettingsDialog open={dialogOpen} setOpen={setDialogOpen} />
    </>
  );
};

export default ModelProviders;
