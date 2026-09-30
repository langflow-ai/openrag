"use client";

import { ArrowUpRight, Loader2 } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { useGetModelCatalogQuery } from "@/app/api/queries/useGetModelsQuery";
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
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { useRegisterDirty } from "@/contexts/unsaved-changes-context";
import { trackButton } from "@/lib/analytics";
import { DEFAULT_AGENT_SETTINGS, UI_CONSTANTS } from "@/lib/constants";
import { resolveLangflowEditUrl } from "@/lib/url-utils";
import { cn } from "@/lib/utils";
import { useUpdateSettingsMutation } from "../../api/mutations/useUpdateSettingsMutation";
import { ModelFeatures } from "../../onboarding/_components/model-features";
import { ModelSelector } from "../../onboarding/_components/model-selector";
import {
  findGroupedSelection,
  groupedCatalogOptions,
} from "../_helpers/catalog-models";
import { getModelLogo } from "../_helpers/model-helpers";
import { LangflowIcon } from "./langflow-icon";

const { MAX_SYSTEM_PROMPT_CHARS } = UI_CONSTANTS;

export function AgentSettingsSection() {
  const isCloudBrand = useIsCloudBrand();
  const { isAuthenticated, isNoAuthMode, isIbmAuthMode, runMode } = useAuth();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const focusLlmModel = searchParams.get("focusLlmModel") === "true";
  const [isRestoringFlow, setIsRestoringFlow] = useState<boolean>(false);
  const [openLlmSelector, setOpenLlmSelector] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState<string>("");
  const [userEdited, setUserEdited] = useState(false);

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const {
    data: catalog,
    isLoading: catalogLoading,
    // The catalogue query does not retry, so a failed fetch leaves the groups
    // empty. Without this flag the selector would tell the user to configure a
    // provider when the real problem is that the catalogue never loaded.
    isError: catalogError,
  } = useGetModelCatalogQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const configuredProviders = useMemo(
    () => ({
      openai: settings.providers?.openai?.configured === true,
      anthropic: settings.providers?.anthropic?.configured === true,
      ollama: settings.providers?.ollama?.configured === true,
      watsonx: settings.providers?.watsonx?.configured === true,
      ...Object.fromEntries(
        Object.entries(settings.providers?.custom ?? {}).map(
          ([provider, value]) => [provider, value.configured === true],
        ),
      ),
    }),
    [settings.providers],
  );

  const groupedLlmModels = useMemo(
    () =>
      groupedCatalogOptions(catalog, configuredProviders, "language").map(
        (group) => ({
          group: group.group,
          provider: group.key,
          icon: getModelLogo("", group.key),
          options: group.options,
        }),
      ),
    [catalog, configuredProviders],
  );

  const isLoadingAnyLlmModels = catalogLoading;

  const updateSettingsMutation = useUpdateSettingsMutation({
    onSuccess: () => {
      toast.success("Settings updated successfully");
    },
    onError: (error) => {
      toast.error("Failed to update settings", { description: error.message });
    },
  });

  const allLlmOptions = useMemo(
    () => groupedLlmModels.flatMap((g) => g.options),
    [groupedLlmModels],
  );
  const selectedLlmMatch = findGroupedSelection(
    groupedLlmModels,
    settings.agent?.llm_model,
    settings.agent?.llm_provider,
  );
  const selectedLlm = selectedLlmMatch?.option;
  const selectedLlmGroup = selectedLlmMatch?.group;

  const handleModelChange = useCallback(
    (newModel: string, provider?: string) => {
      if (newModel && provider) {
        updateSettingsMutation.mutate({
          llm_model: newModel,
          llm_provider: provider,
        });
      } else if (newModel) {
        updateSettingsMutation.mutate({ llm_model: newModel });
      }
    },
    [updateSettingsMutation],
  );

  const autoSelectedLlm = useRef(false);
  useEffect(() => {
    if (settings.agent?.llm_model) {
      autoSelectedLlm.current = false;
      return;
    }
    if (autoSelectedLlm.current) return;
    if (allLlmOptions.length > 0) {
      autoSelectedLlm.current = true;
      const fallback = allLlmOptions.find((o) => o.default) || allLlmOptions[0];
      handleModelChange(fallback.value, fallback.provider);
    }
  }, [settings.agent?.llm_model, allLlmOptions, handleModelChange]);

  const agentDirty = systemPrompt !== (settings.agent?.system_prompt ?? "");
  useRegisterDirty("agent-settings", userEdited && agentDirty);

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
      const timeoutId = setTimeout(() => setOpenLlmSelector(false), 100);
      return () => clearTimeout(timeoutId);
    }
  }, [focusLlmModel, searchParams, router, pathname]);

  const handleSystemPromptSave = () => {
    trackButton({
      CTA: "Save Agent Instructions",
      elementId: "save-agent-instructions-button",
      namespace: "settings",
    });
    updateSettingsMutation.mutate(
      { system_prompt: systemPrompt },
      { onSuccess: () => setUserEdited(false) },
    );
  };

  const handleDisableChatWithLangflowChange = (checked: boolean) => {
    updateSettingsMutation.mutate({ disable_chat_with_langflow: checked });
  };

  const handleEditInLangflow = (closeDialog: () => void) => {
    trackButton({
      CTA: "Edit in Langflow - Agent",
      elementId: "edit-langflow-agent-button",
      namespace: "settings",
    });
    window.open(
      resolveLangflowEditUrl({
        flowId: settings.flow_id,
        editUrlOverride: settings.langflow_edit_url,
        publicUrl: settings.langflow_public_url,
        langflowPort: settings.langflow_port,
        isIbmAuthMode,
        runMode,
      }),
      "_blank",
      "noopener,noreferrer",
    );
    closeDialog();
  };

  const handleRestoreRetrievalFlow = (closeDialog: () => void) => {
    setIsRestoringFlow(true);

    trackButton({
      CTA: "Restore Flow - Agent",
      elementId: "restore-agent-flow-button",
      namespace: "settings",
    });

    fetch("/api/reset-flow/retrieval", { method: "POST" })
      .then((res) =>
        res.text().then((text) => {
          const body = text ? JSON.parse(text) : {};
          if (!res.ok) {
            throw new Error(
              body.error ?? `HTTP ${res.status}: ${res.statusText}`,
            );
          }
        }),
      )
      .then(() => {
        setSystemPrompt(DEFAULT_AGENT_SETTINGS.system_prompt);
        setUserEdited(false);
        toast.success("Default agent flow settings restored successfully");
        closeDialog();
      })
      .catch((err) => {
        console.error("Error restoring retrieval flow:", err);
        toast.error(
          err.message || "Failed to restore default agent flow settings",
        );
        closeDialog();
      })
      .finally(() => setIsRestoringFlow(false));
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
                isLoading={isRestoringFlow}
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
                custom
                noOptionsPlaceholder={
                  isLoadingAnyLlmModels
                    ? "Loading models..."
                    : catalogError
                      ? "Could not load the model catalogue. Retry later."
                      : "No language models detected. Configure a provider first."
                }
                value={settings.agent?.llm_model || ""}
                selectedProvider={settings.agent?.llm_provider}
                onValueChange={handleModelChange}
                defaultOpen={openLlmSelector}
              />
            </LabelWrapper>
            {settings.agent?.llm_model && selectedLlmGroup && (
              <div className="mt-3">
                <ModelFeatures
                  model={
                    selectedLlm?.model ?? { model: settings.agent.llm_model }
                  }
                  providerName={selectedLlmGroup.group}
                  provider={selectedLlmGroup.provider}
                />
              </div>
            )}
          </div>
          <div className="flex items-center justify-between py-3 border-b border-border">
            <div className="flex-1">
              <Label
                htmlFor="disable-chat-with-langflow"
                className="text-base font-medium cursor-pointer pb-3"
              >
                Disable Langflow Chat
              </Label>
              <div className="text-sm text-muted-foreground">
                Run chat in OpenRAG against the language model above instead of
                sending it to the Langflow flow.
              </div>
            </div>
            <Switch
              id="disable-chat-with-langflow"
              checked={settings.agent?.disable_chat_with_langflow ?? false}
              onCheckedChange={handleDisableChatWithLangflowChange}
              disabled={updateSettingsMutation.isPending}
            />
          </div>
          <div className="space-y-2">
            <LabelWrapper label="Agent Instructions" id="system-prompt">
              <Textarea
                id="system-prompt"
                placeholder="Enter your agent instructions here..."
                value={systemPrompt}
                onChange={(e) => {
                  setUserEdited(true);
                  setSystemPrompt(e.target.value);
                }}
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
          <div className="flex justify-end pt-2 gap-2">
            {settings.agent?.default_system_prompt && (
              <Button
                onClick={() => {
                  setUserEdited(true);
                  setSystemPrompt(settings.agent?.default_system_prompt || "");
                }}
                variant="outline"
                size="sm"
                disabled={systemPrompt === settings.agent.default_system_prompt}
              >
                Restore Default
              </Button>
            )}
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
