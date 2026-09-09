"use client";

import { AnimatePresence, domAnimation, LazyMotion, m } from "motion/react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { FormProvider, useForm } from "react-hook-form";
import { toast } from "sonner";
import {
  type AffectedEmbeddingModel,
  isEmbeddingProviderInUseError,
  useUpdateSettingsMutation,
} from "@/app/api/mutations/useUpdateSettingsMutation";
import { useGetModelCatalogQuery } from "@/app/api/queries/useGetModelsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import type { CatalogCredentialField } from "@/components/models/catalog-models";
import {
  canRemoveProvider,
  getProviderChrome,
  type ModelProvider,
} from "@/components/models/model-helpers";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuth } from "@/contexts/auth-context";
import ModelProviderDialogFooter from "./model-provider-dialog-footer";
import {
  ProviderSettingsForm,
  type ProviderSettingsFormData,
} from "./provider-settings-form";

const EMPTY_FIELDS: CatalogCredentialField[] = [];

/**
 * Credential dialog for any provider without a bespoke one.
 *
 * Fields come from the catalogue's per-provider spec and are saved through the
 * generic `provider_credentials` payload, so adding a provider row to
 * `config/model_providers.yaml` is enough to make it configurable here.
 *
 * There is no live key check on save — OpenRAG has no generic
 * "list this provider's models" endpoint to probe with. The credentials are
 * validated the first time a model from this provider is selected in Agent or
 * Ingestion settings, which reports the provider's own error.
 */
const ProviderSettingsDialog = ({
  provider,
  displayName,
  open,
  setOpen,
}: {
  provider: ModelProvider;
  displayName?: string;
  open: boolean;
  setOpen: (open: boolean) => void;
}) => {
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false);
  const [affectedModels, setAffectedModels] = useState<
    AffectedEmbeddingModel[] | undefined
  >(undefined);
  const [azureAuthMethod, setAzureAuthMethod] = useState("api_key");
  const [onPremAuthMethod, setOnPremAuthMethod] = useState("username_api_key");
  const router = useRouter();

  const { data: settings = {} } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });
  const { data: catalog } = useGetModelCatalogQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });

  const chrome = getProviderChrome(provider, displayName);
  const catalogEntry = catalog?.providers?.find(
    (entry) => entry.key === provider,
  );
  const fields = catalogEntry?.credential_fields ?? EMPTY_FIELDS;

  const saved = settings.providers?.custom?.[provider];
  const isConfigured = saved?.configured === true;
  const savedSecretFields = saved?.secret_fields ?? [];
  const formValues = useMemo(
    () =>
      open
        ? {
            credentials: Object.fromEntries(
              fields.map((field) => [
                field.key,
                saved?.credential_values?.[field.key] ?? "",
              ]),
            ),
          }
        : { credentials: {} },
    [fields, open, saved],
  );

  // Removing the last configured provider with an embedding model would leave
  // the agent with nothing to embed documents, so require another one first.
  const canRemove = canRemoveProvider(settings.providers, provider);

  const methods = useForm<ProviderSettingsFormData>({
    mode: "onSubmit",
    values: formValues,
  });

  const savedAuthMethod = saved?.auth_method;
  const authMethodSeed = `${open}:${provider}:${savedAuthMethod ?? ""}`;
  const [previousAuthMethodSeed, setPreviousAuthMethodSeed] =
    useState<string>();
  if (authMethodSeed !== previousAuthMethodSeed) {
    setPreviousAuthMethodSeed(authMethodSeed);
    if (provider === "azure") setAzureAuthMethod(savedAuthMethod ?? "api_key");
    if (provider === "watsonx_onprem") {
      setOnPremAuthMethod(savedAuthMethod ?? "username_api_key");
    }
  }

  const { handleSubmit } = methods;

  const settingsMutation = useUpdateSettingsMutation({
    onSuccess: () => {
      toast.message(`${chrome.name} successfully configured`, {
        description: "You can now select its models in Settings.",
        duration: Infinity,
        closeButton: true,
        action: {
          label: "Settings",
          onClick: () => {
            router.push("/settings/agent?focusLlmModel=true");
          },
        },
      });
      setOpen(false);
    },
  });

  const removeMutation = useUpdateSettingsMutation({
    onSuccess: () => {
      toast.success(`${chrome.name} configuration removed`);
      setShowRemoveConfirm(false);
      setAffectedModels(undefined);
      setOpen(false);
    },
    onError: (err) => {
      if (isEmbeddingProviderInUseError(err)) {
        setAffectedModels(err.affectedModels);
      }
    },
  });

  const onSubmit = (data: ProviderSettingsFormData) => {
    // Blank means "leave the stored value alone": the backend ignores empty
    // values, and secrets are never echoed back for us to resubmit.
    const credentials: Record<string, string> = {};
    const azureAuthFields: Record<string, Set<string>> = {
      api_key: new Set(["api_key"]),
      entra_token: new Set(["azure_ad_token"]),
      service_principal: new Set(["tenant_id", "client_id", "client_secret"]),
    };
    const allowedAzureFields = new Set([
      "api_base",
      "api_version",
      ...(azureAuthFields[azureAuthMethod] ?? []),
    ]);
    const allowedOnPremFields = new Set([
      "api_base",
      "space_id",
      "project_id",
      ...(onPremAuthMethod === "zen_api_key"
        ? ["zen_api_key"]
        : ["username", "api_key"]),
    ]);
    for (const [key, value] of Object.entries(data.credentials ?? {})) {
      if (provider === "azure" && !allowedAzureFields.has(key)) {
        continue;
      }
      if (provider === "watsonx_onprem" && !allowedOnPremFields.has(key))
        continue;
      const trimmed = (value ?? "").trim();
      if (trimmed !== "") {
        credentials[key] = trimmed;
      }
    }

    if (Object.keys(credentials).length === 0) {
      methods.setError("root", { message: "Enter at least one credential" });
      return;
    }

    settingsMutation.mutate({
      provider_credentials: { [provider]: credentials },
      ...(provider === "azure"
        ? { provider_auth_methods: { azure: azureAuthMethod } }
        : provider === "watsonx_onprem"
          ? { provider_auth_methods: { watsonx_onprem: onPremAuthMethod } }
          : {}),
    });
  };

  const Logo = chrome.logo;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setShowRemoveConfirm(false);
        setAffectedModels(undefined);
        setOpen(o);
      }}
    >
      <DialogContent
        autoFocus={false}
        className="max-w-2xl max-h-[95vh] flex flex-col overflow-hidden"
      >
        <FormProvider {...methods}>
          <form
            onSubmit={handleSubmit(onSubmit)}
            className="flex flex-col min-h-0 flex-1"
          >
            <DialogHeader className="shrink-0 mb-2">
              <DialogTitle className="flex items-center gap-3">
                <div className="w-8 h-8 rounded flex items-center justify-center bg-white border">
                  <Logo className="w-4 h-4 text-black" />
                </div>
                {chrome.name} Setup
              </DialogTitle>
            </DialogHeader>

            <div className="flex-1 min-h-0 overflow-y-auto min-w-0 px-1 -mx-1 py-1 space-y-4">
              <ProviderSettingsForm
                provider={provider}
                providerName={chrome.name}
                fields={fields}
                savedSecretFields={savedSecretFields}
                saveError={methods.formState.errors.root?.message}
                azureAuthMethod={azureAuthMethod}
                onAzureAuthMethodChange={setAzureAuthMethod}
                onPremAuthMethod={onPremAuthMethod}
                onOnPremAuthMethodChange={setOnPremAuthMethod}
              />

              <LazyMotion features={domAnimation}>
                <AnimatePresence mode="wait">
                  {settingsMutation.isError && (
                    <m.div
                      key="error"
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -10 }}
                    >
                      <p className="rounded-lg border border-destructive p-4 min-w-0 [overflow-wrap:anywhere]">
                        {settingsMutation.error?.message}
                      </p>
                    </m.div>
                  )}
                  {removeMutation.isError &&
                    !isEmbeddingProviderInUseError(removeMutation.error) && (
                      <m.div
                        key="remove-error"
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -10 }}
                      >
                        <p className="rounded-lg border border-destructive p-4 min-w-0 [overflow-wrap:anywhere]">
                          {removeMutation.error?.message}
                        </p>
                      </m.div>
                    )}
                </AnimatePresence>
              </LazyMotion>
            </div>

            <div className="shrink-0">
              <ModelProviderDialogFooter
                showRemoveConfirm={showRemoveConfirm}
                onCancelRemove={() => {
                  setShowRemoveConfirm(false);
                  setAffectedModels(undefined);
                }}
                onConfirmRemove={() =>
                  removeMutation.mutate({
                    remove_provider_config: provider,
                    force_remove: !!affectedModels,
                  })
                }
                isRemovePending={removeMutation.isPending}
                isConfigured={isConfigured}
                canRemove={canRemove}
                providerKey={provider}
                removeDisabledTooltip={`Configure another model provider before removing ${chrome.name}`}
                onRequestRemove={() => setShowRemoveConfirm(true)}
                onCancel={() => setOpen(false)}
                isSavePending={settingsMutation.isPending}
                isValidating={false}
                affectedModels={affectedModels}
              />
            </div>
          </form>
        </FormProvider>
      </DialogContent>
    </Dialog>
  );
};

export default ProviderSettingsDialog;
