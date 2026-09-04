"use client";

import { AnimatePresence, domAnimation, LazyMotion, m } from "motion/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
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

  // Removing the last configured provider would leave the agent with nothing
  // to call, so mirror the bespoke dialogs and require another one first.
  const canRemove =
    isConfigured &&
    Object.entries(settings.providers?.custom ?? {}).some(
      ([key, value]) => key !== provider && value?.configured === true,
    );

  const methods = useForm<ProviderSettingsFormData>({
    mode: "onSubmit",
    defaultValues: { credentials: {} },
  });

  // Seed on open, and again if the catalogue or the saved settings land after
  // it. Both are react-query results, so their identity is stable while the
  // dialog is open and this cannot stomp on what the user is typing.
  useEffect(() => {
    if (!open) {
      return;
    }
    methods.reset({
      credentials: Object.fromEntries(
        fields.map((field) => [
          field.key,
          saved?.credential_values?.[field.key] ?? "",
        ]),
      ),
    });
  }, [open, fields, saved, methods]);

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
    for (const [key, value] of Object.entries(data.credentials ?? {})) {
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
      <DialogContent autoFocus={false} className="max-w-2xl overflow-hidden">
        <FormProvider {...methods}>
          <form
            onSubmit={handleSubmit(onSubmit)}
            className="grid min-w-0 gap-4"
          >
            <DialogHeader className="mb-2">
              <DialogTitle className="flex items-center gap-3">
                <div className="w-8 h-8 rounded flex items-center justify-center bg-white border">
                  <Logo className="w-4 h-4 text-black" />
                </div>
                {chrome.name} Setup
              </DialogTitle>
            </DialogHeader>

            <ProviderSettingsForm
              providerName={chrome.name}
              fields={fields}
              savedSecretFields={savedSecretFields}
              saveError={methods.formState.errors.root?.message}
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
          </form>
        </FormProvider>
      </DialogContent>
    </Dialog>
  );
};

export default ProviderSettingsDialog;
