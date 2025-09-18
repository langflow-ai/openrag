"use client";

import { Suspense, useState } from "react";
import { toast } from "sonner";
import { useUpdateFlowSettingMutation } from "@/app/api/mutations/useUpdateFlowSettingMutation";
import {
  type Settings,
  useGetSettingsQuery,
} from "@/app/api/queries/useGetSettingsQuery";
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
import { useAuth } from "@/contexts/auth-context";
import { IBMOnboarding } from "./ibm-onboarding";
import { OllamaOnboarding } from "./ollama-onboarding";
import { OpenAIOnboarding } from "./openai-onboarding";

function OnboardingPage() {
  const { isAuthenticated } = useAuth();

  const [modelProvider, setModelProvider] = useState<string>("openai");

  const [sampleDataset, setSampleDataset] = useState<boolean>(false);
  // Fetch settings using React Query
  const { data: settingsDb = {} } = useGetSettingsQuery({
    enabled: isAuthenticated,
  });

  const [settings, setSettings] = useState<Settings>(settingsDb);

  // Mutations
  const updateFlowSettingMutation = useUpdateFlowSettingMutation({
    onSuccess: () => {
      console.log("Setting updated successfully");
    },
    onError: (error) => {
      toast.error("Failed to update settings", {
        description: error.message,
      });
    },
  });

  const handleComplete = () => {
    updateFlowSettingMutation.mutate({
      llm_model: settings.agent?.llm_model,
      embedding_model: settings.knowledge?.embedding_model,
      system_prompt: settings.agent?.system_prompt,
    });
  };

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
          <Tabs defaultValue={modelProvider} onValueChange={setModelProvider}>
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
                  settings={settings}
                  setSettings={setSettings}
                  sampleDataset={sampleDataset}
                  setSampleDataset={setSampleDataset}
                />
              </TabsContent>
              <TabsContent value="watsonx">
                <IBMOnboarding
                  settings={settings}
                  setSettings={setSettings}
                  sampleDataset={sampleDataset}
                  setSampleDataset={setSampleDataset}
                />
              </TabsContent>
              <TabsContent value="ollama">
                <OllamaOnboarding
                  settings={settings}
                  setSettings={setSettings}
                  sampleDataset={sampleDataset}
                  setSampleDataset={setSampleDataset}
                />
              </TabsContent>
            </CardContent>
          </Tabs>
          <CardFooter className="flex justify-end">
            <Button size="sm" onClick={handleComplete}>
              Complete
            </Button>
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
