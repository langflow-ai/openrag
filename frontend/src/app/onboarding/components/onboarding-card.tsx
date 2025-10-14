"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  type OnboardingVariables,
  useOnboardingMutation,
} from "@/app/api/mutations/useOnboardingMutation";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import IBMLogo from "@/components/logo/ibm-logo";
import OllamaLogo from "@/components/logo/ollama-logo";
import OpenAILogo from "@/components/logo/openai-logo";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { IBMOnboarding } from "./ibm-onboarding";
import { OllamaOnboarding } from "./ollama-onboarding";
import { OpenAIOnboarding } from "./openai-onboarding";

const OnboardingCard = ({
  isDoclingHealthy,
  boarderless = false,
}: {
  isDoclingHealthy: boolean;
  boarderless?: boolean;
}) => {
  const { data: settingsDb, isLoading: isSettingsLoading } =
  useGetSettingsQuery();

  const redirect = "/";
  const router = useRouter();

  // Redirect if already authenticated or in no-auth mode
  useEffect(() => {
    if (!isSettingsLoading && settingsDb && settingsDb.edited) {
      router.push(redirect);
    }
  }, [isSettingsLoading, settingsDb, router]);


  const [modelProvider, setModelProvider] = useState<string>("openai");

  const [sampleDataset, setSampleDataset] = useState<boolean>(true);

  const handleSetModelProvider = (provider: string) => {
    setModelProvider(provider);
    setSettings({
      model_provider: provider,
      embedding_model: "",
      llm_model: "",
    });
  };

  const [settings, setSettings] = useState<OnboardingVariables>({
    model_provider: modelProvider,
    embedding_model: "",
    llm_model: "",
  });

  // Mutations
  const onboardingMutation = useOnboardingMutation({
    onSuccess: (data) => {
      console.log("Onboarding completed successfully", data);
      router.push(redirect);
    },
    onError: (error) => {
      toast.error("Failed to complete onboarding", {
        description: error.message,
      });
    },
  });

  const handleComplete = () => {
    if (
      !settings.model_provider ||
      !settings.llm_model ||
      !settings.embedding_model
    ) {
      toast.error("Please complete all required fields");
      return;
    }

    // Prepare onboarding data
    const onboardingData: OnboardingVariables = {
      model_provider: settings.model_provider,
      llm_model: settings.llm_model,
      embedding_model: settings.embedding_model,
      sample_data: sampleDataset,
    };

    // Add API key if available
    if (settings.api_key) {
      onboardingData.api_key = settings.api_key;
    }

    // Add endpoint if available
    if (settings.endpoint) {
      onboardingData.endpoint = settings.endpoint;
    }

    // Add project_id if available
    if (settings.project_id) {
      onboardingData.project_id = settings.project_id;
    }

    onboardingMutation.mutate(onboardingData);
  };

  const isComplete = !!settings.llm_model && !!settings.embedding_model && isDoclingHealthy;

  return (
    <Card className={`w-full max-w-[600px] ${boarderless ? "border-none" : ""}`}>
      <Tabs
        defaultValue={modelProvider}
        onValueChange={handleSetModelProvider}
      >
        <CardHeader>
          <TabsList>
            <TabsTrigger value="openai">
              <OpenAILogo className="w-4 h-4" />
              OpenAI
            </TabsTrigger>
            <TabsTrigger value="watsonx">
              <IBMLogo className="w-4 h-4" />
              IBM watsonx.ai
            </TabsTrigger>
            <TabsTrigger value="ollama">
              <OllamaLogo className="w-4 h-4" />
              Ollama
            </TabsTrigger>
          </TabsList>
        </CardHeader>
        <CardContent>
          <TabsContent value="openai">
            <OpenAIOnboarding
              setSettings={setSettings}
              sampleDataset={sampleDataset}
              setSampleDataset={setSampleDataset}
            />
          </TabsContent>
          <TabsContent value="watsonx">
            <IBMOnboarding
              setSettings={setSettings}
              sampleDataset={sampleDataset}
              setSampleDataset={setSampleDataset}
            />
          </TabsContent>
          <TabsContent value="ollama">
            <OllamaOnboarding
              setSettings={setSettings}
              sampleDataset={sampleDataset}
              setSampleDataset={setSampleDataset}
            />
          </TabsContent>
        </CardContent>
      </Tabs>
      <CardFooter className="flex justify-end">
        <Tooltip>
          <TooltipTrigger asChild>
            <div>
              <Button
                size="sm"
                onClick={handleComplete}
                disabled={!isComplete}
                loading={onboardingMutation.isPending}
              >
                <span className="select-none">Complete</span>
              </Button>
            </div>
          </TooltipTrigger>
          {!isComplete && (
            <TooltipContent>
              {!!settings.llm_model && !!settings.embedding_model && !isDoclingHealthy
                ? "docling-serve must be running to continue"
                : "Please fill in all required fields"}
            </TooltipContent>
          )}
        </Tooltip>
      </CardFooter>
    </Card>
  )
}

export default OnboardingCard;
