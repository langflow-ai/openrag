"use client";

import { ArrowUpRight, Loader2 } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  useGetAnthropicModelsQuery,
  useGetIBMModelsQuery,
  useGetOllamaModelsQuery,
  useGetOpenAIModelsQuery,
} from "@/app/api/queries/useGetModelsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { ConfirmationDialog } from "@/components/confirmation-dialog";
import { LabelWrapper } from "@/components/label-wrapper";
import { RequirePermission } from "@/components/require-permission";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { DEFAULT_AGENT_SETTINGS, UI_CONSTANTS } from "@/lib/constants";
import { deriveCloudLangflowUrl } from "@/lib/url-utils";
import { cn } from "@/lib/utils";
import { useUpdateSettingsMutation } from "../../api/mutations/useUpdateSettingsMutation";
import { ModelSelector } from "../../onboarding/_components/model-selector";
import { getModelLogo } from "../_helpers/model-helpers";
import { LangflowIcon } from "./langflow-icon";

const { MAX_SYSTEM_PROMPT_CHARS } = UI_CONSTANTS;

export function AgentSettingsSection() {
  const isCloudBrand = useIsCloudBrand();
  const { isAuthenticated, isNoAuthMode, isIbmAuthMode } = useAuth();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const focusLlmModel = searchParams.get("focusLlmModel") === "true";
  const [openLlmSelector, setOpenLlmSelector] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState<string>("");

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const { data: openaiModels, isLoading: openaiLoading } =
    useGetOpenAIModelsQuery(
      { apiKey: "" },
      { enabled: settings?.providers?.openai?.configured === true },
    );
  const { data: anthropicModels, isLoading: anthropicLoading } =
    useGetAnthropicModelsQuery(
      { apiKey: "" },
      { enabled: settings?.providers?.anthropic?.configured === true },
    );
  const { data: ollamaModels, isLoading: ollamaLoading } =
    useGetOllamaModelsQuery(
      { endpoint: settings?.providers?.ollama?.endpoint },
      {
        enabled:
          settings?.providers?.ollama?.configured === true &&
          !!settings?.providers?.ollama?.endpoint,
      },
    );
  const { data: watsonxModels, isLoading: watsonxLoading } =
    useGetIBMModelsQuery(
      {
        endpoint: settings?.providers?.watsonx?.endpoint,
        apiKey: "",
        projectId: settings?.providers?.watsonx?.project_id,
      },
      {
        enabled:
          settings?.providers?.watsonx?.configured === true &&
          !!settings?.providers?.watsonx?.endpoint &&
          !!settings?.providers?.watsonx?.project_id,
      },
    );

  const groupedLlmModels = [
    {
      group: "OpenAI",
      provider: "openai",
      icon: getModelLogo("", "openai"),
      models: openaiModels?.language_models || [],
      configured: settings.providers?.openai?.configured === true,
    },
    {
      group: "Anthropic",
      provider: "anthropic",
      icon: getModelLogo("", "anthropic"),
      models: anthropicModels?.language_models || [],
      configured: settings.providers?.anthropic?.configured === true,
    },
    {
      group: "Ollama",
      provider: "ollama",
      icon: getModelLogo("", "ollama"),
      models: ollamaModels?.language_models || [],
      configured: settings.providers?.ollama?.configured === true,
    },
    {
      group: "IBM watsonx.ai",
      provider: "watsonx",
      icon: getModelLogo("", "watsonx"),
      models: watsonxModels?.language_models || [],
      configured: settings.providers?.watsonx?.configured === true,
    },
  ]
    .filter((p) => p.configured)
    .map((p) => ({
      group: p.group,
      icon: p.icon,
      options: p.models.map((m) => ({ ...m, provider: p.provider })),
    }));

  const isLoadingAnyLlmModels =
    openaiLoading || anthropicLoading || ollamaLoading || watsonxLoading;

  const updateSettingsMutation = useUpdateSettingsMutation({
    onSuccess: () => {
      toast.success("Settings updated successfully");
    },
    onError: (error) => {
      toast.error("Failed to update settings", { description: error.message });
    },
  });

  useEffect(() => {
    if (settings.agent?.system_prompt) {
      setSystemPrompt(settings.agent.system_prompt);
    }
  }, [settings.agent?.system_prompt]);

  useEffect(() => {
    if (focusLlmModel) {
      setOpenLlmSelector(true);
      const agentCard = document.getElementById("agent-card");
      if (agentCard)
        agentCard.scrollIntoView({ behavior: "smooth", block: "start" });
      const newParams = new URLSearchParams(searchParams.toString());
      newParams.delete("focusLlmModel");
      router.replace(`${pathname}?${newParams.toString()}`, { scroll: false });
      setTimeout(() => setOpenLlmSelector(false), 100);
    }
  }, [focusLlmModel, searchParams, router, pathname]);

  const handleModelChange = (newModel: string, provider?: string) => {
    if (newModel && provider) {
      updateSettingsMutation.mutate({
        llm_model: newModel,
        llm_provider: provider,
      });
    } else if (newModel) {
      updateSettingsMutation.mutate({ llm_model: newModel });
    }
  };

  const handleSystemPromptSave = () => {
    updateSettingsMutation.mutate({ system_prompt: systemPrompt });
  };

  const handleEditInLangflow = (closeDialog: () => void) => {
    const cloudLangflowUrl =
      isIbmAuthMode && typeof window !== "undefined"
        ? deriveCloudLangflowUrl(window.location.origin)
        : null;
    const derivedFromWindow =
      typeof window !== "undefined"
        ? `${window.location.protocol}//${window.location.hostname}:7860`
        : "";
    const base = (
      cloudLangflowUrl ||
      settings.langflow_public_url ||
      derivedFromWindow ||
      "http://localhost:7860"
    ).replace(/\/$/, "");
    const computed = settings.flow_id
      ? `${base}/flow/${settings.flow_id}`
      : base;
    window.open(
      settings.langflow_edit_url || computed,
      "_blank",
      "noopener,noreferrer",
    );
    closeDialog();
  };

  const handleRestoreRetrievalFlow = (closeDialog: () => void) => {
    fetch("/api/reset-flow/retrieval", { method: "POST" })
      .then((res) => {
        if (res.ok) return res.json();
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      })
      .then(() => {
        setSystemPrompt(DEFAULT_AGENT_SETTINGS.system_prompt);
        closeDialog();
      })
      .catch((err) => {
        console.error("Error restoring retrieval flow:", err);
        closeDialog();
      });
  };

  return (
    <Card id="agent-card">
      <CardHeader>
        <div className="flex items-center justify-between mb-3">
          <CardTitle
            className={cn(
              "text-lg",
              isCloudBrand && "ibm-settings-section-title",
            )}
          >
            Agent
          </CardTitle>
          <RequirePermission perm="flows:edit">
            <div className="flex gap-2">
              <ConfirmationDialog
                trigger={
                  <Button ignoreTitleCase={true} variant="outline">
                    Restore flow
                  </Button>
                }
                title="Restore default Agent flow"
                description="This restores defaults and discards all custom settings and overrides. This can't be undone."
                confirmText="Restore"
                variant="destructive"
                onConfirm={handleRestoreRetrievalFlow}
              />
              <ConfirmationDialog
                trigger={
                  <Button>
                    <LangflowIcon />
                    Edit in Langflow
                  </Button>
                }
                title="Edit Agent flow in Langflow"
                description={
                  <>
                    <p className="mb-2">
                      You&apos;re entering Langflow. You can edit the{" "}
                      <b>Agent flow</b> and other underlying flows. Manual
                      changes to components, wiring, or I/O can break this
                      experience.
                    </p>
                    <p className="mb-2">
                      To enable editing, you need to unlock the flow by clicking
                      on its name and disabling the <b>Lock flow</b> option.
                    </p>
                    <p>You can restore this flow from Settings.</p>
                  </>
                }
                confirmText="Proceed"
                confirmIcon={<ArrowUpRight />}
                onConfirm={handleEditInLangflow}
                variant="warning"
              />
            </div>
          </RequirePermission>
        </div>
        <CardDescription>
          This Agent retrieves from your knowledge and generates chat responses.
          Edit in Langflow for full control.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          <div className="space-y-2">
            <LabelWrapper
              label="Language model"
              helperText="Model used for chat"
              id="language-model"
              required={true}
            >
              <ModelSelector
                groupedOptions={groupedLlmModels}
                noOptionsPlaceholder={
                  isLoadingAnyLlmModels
                    ? "Loading models..."
                    : "No language models detected. Configure a provider first."
                }
                value={settings.agent?.llm_model || ""}
                onValueChange={handleModelChange}
                defaultOpen={openLlmSelector}
              />
            </LabelWrapper>
          </div>
          <div className="space-y-2">
            <LabelWrapper label="Agent Instructions" id="system-prompt">
              <Textarea
                id="system-prompt"
                placeholder="Enter your agent instructions here..."
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                rows={6}
                className={`resize-none ${
                  systemPrompt.length > MAX_SYSTEM_PROMPT_CHARS
                    ? "!border-destructive focus:border-destructive"
                    : ""
                }`}
              />
            </LabelWrapper>
            <span
              className={`text-xs ${
                systemPrompt.length > MAX_SYSTEM_PROMPT_CHARS
                  ? "text-destructive"
                  : "text-muted-foreground"
              }`}
            >
              {systemPrompt.length}/{MAX_SYSTEM_PROMPT_CHARS} characters
            </span>
          </div>
          <div className="flex justify-end pt-2">
            <Button
              onClick={handleSystemPromptSave}
              disabled={
                updateSettingsMutation.isPending ||
                systemPrompt.length > MAX_SYSTEM_PROMPT_CHARS
              }
              className="min-w-[120px]"
              size="sm"
              variant="outline"
            >
              {updateSettingsMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Saving...
                </>
              ) : (
                "Save Agent Instructions"
              )}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
