"use client";

import { Suspense, useState } from "react";
import { useUpdateFlowSettingMutation } from "@/app/api/mutations/useUpdateFlowSettingMutation";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import IBMLogo from "@/components/logo/ibm-logo";
import OllamaLogo from "@/components/logo/ollama-logo";
import OpenAILogo from "@/components/logo/openai-logo";
import { ProtectedRoute } from "@/components/protected-route";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/contexts/auth-context";
import { AdvancedOnboarding } from "./advanced";

function OnboardingPage() {
  const { isAuthenticated } = useAuth();

  const [modelProvider, setModelProvider] = useState<string>("openai");
  // Fetch settings using React Query
  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated,
  });

  // Mutations
  const updateFlowSettingMutation = useUpdateFlowSettingMutation({
    onSuccess: () => {
      console.log("Setting updated successfully");
    },
    onError: (error) => {
      console.error("Failed to update setting:", error.message);
    },
  });

  return (
    <div
      className="min-h-dvh relative flex gap-5 flex-col items-center justify-center bg-background p-4"
      style={{
        backgroundImage: "url('/images/background.png')",
        backgroundSize: "cover",
        backgroundPosition: "center",
      }}
    >
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
              <AdvancedOnboarding modelProvider={modelProvider} />
            </TabsContent>
            <TabsContent value="watsonx">
              <AdvancedOnboarding modelProvider={modelProvider} />
            </TabsContent>
            <TabsContent value="ollama">
              <AdvancedOnboarding modelProvider={modelProvider} />
            </TabsContent>
          </CardContent>
        </Tabs>
      </Card>
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
