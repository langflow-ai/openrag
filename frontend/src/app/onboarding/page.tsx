"use client";

import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  useOnboardingMutation,
  type OnboardingVariables,
} from "@/app/api/mutations/useOnboardingMutation";
import IBMLogo from "@/components/logo/ibm-logo";
import OllamaLogo from "@/components/logo/ollama-logo";
import OpenAILogo from "@/components/logo/openai-logo";
import { ProtectedRoute } from "@/components/protected-route";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { IBMOnboarding } from "./components/ibm-onboarding";
import { OllamaOnboarding } from "./components/ollama-onboarding";
import { OpenAIOnboarding } from "./components/openai-onboarding";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useGetSettingsQuery } from "../api/queries/useGetSettingsQuery";
import { useRouter } from "next/navigation";

function OnboardingPage() {
  const { data: settingsDb, isLoading: isSettingsLoading } =
    useGetSettingsQuery();

  const redirect = "/";

  const router = useRouter();

  // Redirect if already authenticated or in no-auth mode
  useEffect(() => {
    if (!isSettingsLoading && settingsDb && settingsDb.edited) {
      router.push(redirect);
    }
  }, [isSettingsLoading, redirect]);

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
      toast.success("Onboarding completed successfully!");
      console.log("Onboarding completed successfully", data);
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

  const isComplete = !!settings.llm_model && !!settings.embedding_model;

  return (
    <div
      className="min-h-dvh w-full flex gap-5 flex-col items-center justify-center bg-background p-4"
      style={{
        backgroundImage: "url('/images/background.png')",
        backgroundSize: "cover",
        backgroundPosition: "center",
      }}
    >
      <div className="flex flex-col items-center gap-5 min-h-[550px] w-full">
        <div className="flex flex-col items-center justify-center gap-4">
          <h1 className="text-2xl font-medium font-chivo">
            Configure your models
          </h1>
          <p className="text-sm text-muted-foreground">[description of task]</p>
        </div>
        <Card className="w-full max-w-[580px]">
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
                  IBM
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
                <Button
                  size="sm"
                  onClick={handleComplete}
                  disabled={!isComplete}
                  loading={onboardingMutation.isPending}
                >
                  Complete
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                {!isComplete ? "Please fill in all required fields" : ""}
              </TooltipContent>
            </Tooltip>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
}

export default function ProtectedOnboardingPage() {
  return (
    <ProtectedRoute>
      <Suspense fallback={<div>Loading onboarding...</div>}>
        <OnboardingPage />
      </Suspense>
    </ProtectedRoute>
  );
}
