"use client";

import { Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { useConnectConnectorMutation } from "@/app/api/mutations/useConnectConnectorMutation";
import {
  useClearConnectorOAuthConfigMutation,
  useSaveConnectorOAuthConfigMutation,
} from "@/app/api/mutations/useConnectorOAuthConfigMutation";
import { useConnectorOAuthConfigQuery } from "@/app/api/queries/useConnectorOAuthConfigQuery";
import {
  type ConnectorAccessItem,
  useGetConnectorAccessQuery,
  useUpdateConnectorAccessMutation,
} from "@/app/api/queries/useGetConnectorsQuery";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { LabelWrapper } from "@/components/label-wrapper";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { type Status, StatusBadge } from "@/components/ui/status-badge";
import { Switch } from "@/components/ui/switch";
import { trackButton } from "@/lib/analytics";

interface OAuthCredentialGroup {
  credentialKey: string;
  label: string;
  memberConnectorTypes: string[];
  /** Connector type used to drive the browser OAuth consent check. */
  testConnectorType: string;
}

// Google Drive and Microsoft Graph are the only OAuth-kind connectors today.
// OneDrive + SharePoint share one Microsoft Graph app registration, so they
// collapse into a single credential entry here even though enable/disable
// access stays per connector type.
const OAUTH_CREDENTIAL_GROUPS: OAuthCredentialGroup[] = [
  {
    credentialKey: "google_drive",
    label: "Google Drive",
    memberConnectorTypes: ["google_drive"],
    testConnectorType: "google_drive",
  },
  {
    credentialKey: "microsoft_graph",
    label: "Microsoft Graph (OneDrive & SharePoint)",
    memberConnectorTypes: ["onedrive", "sharepoint"],
    testConnectorType: "onedrive",
  },
];

const OAUTH_MEMBER_TYPES = new Set(
  OAUTH_CREDENTIAL_GROUPS.flatMap((g) => g.memberConnectorTypes),
);

function credentialStatus(entry?: {
  client_id_set: boolean;
  secret_source: "override" | "env" | "none";
}): Status {
  if (!entry) return "not-configured";
  if (entry.client_id_set && entry.secret_source === "override") return "ready";
  if (entry.secret_source === "env") return "fallback";
  return "not-configured";
}

export function ConnectorAccessSection() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const {
    data: connectors = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useGetConnectorAccessQuery();
  const updateAccess = useUpdateConnectorAccessMutation();
  const { data: apiSettings } = useGetSettingsQuery();
  const showOAuthOverrides =
    apiSettings?.show_workspace_oauth_overrides ?? false;
  const { data: oauthConfig = {} } = useConnectorOAuthConfigQuery({
    enabled: showOAuthOverrides,
  });
  const saveOAuthConfig = useSaveConnectorOAuthConfigMutation();
  const clearOAuthConfig = useClearConnectorOAuthConfigMutation();
  const testConnection = useConnectConnectorMutation();

  /** Non-null only after the user edits; server data stays the source of truth until then. */
  const [userDraft, setUserDraft] = useState<Record<string, boolean> | null>(
    null,
  );
  const [credentialDrafts, setCredentialDrafts] = useState<
    Record<string, { client_id: string; client_secret: string }>
  >({});

  // Surface the Test Connection result once the OAuth callback redirects back here.
  useEffect(() => {
    const oauthTest = searchParams.get("oauth_test");
    if (!oauthTest) return;
    const credential = searchParams.get("credential");
    if (oauthTest === "success") {
      toast.success(
        credential
          ? `Test connection succeeded (${credential})`
          : "Test connection succeeded",
      );
    } else {
      toast.error("Test connection failed");
    }
    router.replace("/settings/connector-access");
    // Only re-run when the query params themselves change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const _serverSnapshot = useMemo(
    () => connectors.map((c) => `${c.type}:${c.enabled}`).join("|"),
    [connectors],
  );

  // Reset draft when server data catches up; keep unsaved edits on refetch/focus.
  useEffect(() => {
    setUserDraft((draft) => {
      if (!draft) return null;
      const hasUnsavedEdits = connectors.some(
        (c) => draft[c.type] !== c.enabled,
      );
      return hasUnsavedEdits ? draft : null;
    });
  }, [connectors]);

  const accessForSave = useMemo(
    () =>
      Object.fromEntries(
        connectors.map((c) => [c.type, userDraft?.[c.type] ?? c.enabled]),
      ),
    [connectors, userDraft],
  );

  const isDirty = useMemo(() => {
    if (!userDraft) return false;
    return connectors.some((c) => userDraft[c.type] !== c.enabled);
  }, [connectors, userDraft]);

  const nonOAuthConnectors = showOAuthOverrides
    ? connectors.filter((c) => !OAUTH_MEMBER_TYPES.has(c.type))
    : connectors;

  const renderSwitchRow = (connector: ConnectorAccessItem) => {
    const enabled = userDraft?.[connector.type] ?? connector.enabled;
    return (
      <li
        key={connector.type}
        className="flex items-center justify-between gap-4 rounded-lg bg-muted/20 px-5 py-4"
      >
        <div className="min-w-0">
          <p className="text-sm font-medium">{connector.name}</p>
          <p className="text-xs text-muted-foreground">
            {enabled
              ? "Available in this workspace"
              : "Disabled for this workspace"}
          </p>
        </div>
        <Switch
          checked={enabled}
          disabled={updateAccess.isPending}
          aria-label={`${enabled ? "Disable" : "Enable"} ${connector.name} for this workspace`}
          onCheckedChange={(checked) => {
            setUserDraft((prev) => {
              const base =
                prev ??
                Object.fromEntries(connectors.map((c) => [c.type, c.enabled]));
              return { ...base, [connector.type]: checked };
            });
          }}
        />
      </li>
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg ibm-settings-section-title">
          Connector Settings
        </CardTitle>
        <CardDescription className="text-sm">
          {showOAuthOverrides
            ? "Control which connectors are available in this workspace, and configure OAuth app credentials for connectors that support it — overriding the environment-configured defaults."
            : "Control which connectors are available in this workspace for everyone, including admins."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading…
          </div>
        ) : isError ? (
          <div className="space-y-3 text-sm">
            <p className="text-destructive">
              {error instanceof Error
                ? error.message
                : "Failed to load connectors permission"}
            </p>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => refetch()}
            >
              Retry
            </Button>
          </div>
        ) : (
          <>
            {showOAuthOverrides && (
              <Accordion type="single" collapsible className="space-y-3 mb-4">
                {OAUTH_CREDENTIAL_GROUPS.map((group) => {
                  const memberConnectors = connectors.filter((c) =>
                    group.memberConnectorTypes.includes(c.type),
                  );
                  if (memberConnectors.length === 0) return null;

                  const status = oauthConfig[group.credentialKey];
                  const draft = credentialDrafts[group.credentialKey] ?? {
                    client_id: "",
                    client_secret: "",
                  };
                  const setDraft = (
                    patch: Partial<{
                      client_id: string;
                      client_secret: string;
                    }>,
                  ) =>
                    setCredentialDrafts((prev) => ({
                      ...prev,
                      [group.credentialKey]: { ...draft, ...patch },
                    }));
                  const badgeStatus = credentialStatus(status);

                  return (
                    <AccordionItem
                      key={group.credentialKey}
                      value={group.credentialKey}
                    >
                      <AccordionTrigger>
                        <div className="flex flex-1 items-center justify-between gap-3 pr-2">
                          <span className="text-foreground">{group.label}</span>
                          <StatusBadge status={badgeStatus} />
                        </div>
                      </AccordionTrigger>
                      <AccordionContent className="space-y-5">
                        <ul className="space-y-3">
                          {memberConnectors.map(renderSwitchRow)}
                        </ul>

                        <div className="space-y-4 border-t pt-4">
                          <LabelWrapper
                            label="Client ID"
                            id={`${group.credentialKey}-client-id`}
                          >
                            <Input
                              id={`${group.credentialKey}-client-id`}
                              value={draft.client_id || status?.client_id || ""}
                              onChange={(e) =>
                                setDraft({ client_id: e.target.value })
                              }
                              placeholder="OAuth client ID"
                              autoComplete="off"
                            />
                          </LabelWrapper>
                          <LabelWrapper
                            label="Client Secret"
                            id={`${group.credentialKey}-client-secret`}
                          >
                            <Input
                              id={`${group.credentialKey}-client-secret`}
                              type="password"
                              value={draft.client_secret}
                              onChange={(e) =>
                                setDraft({ client_secret: e.target.value })
                              }
                              placeholder={
                                status?.secret_source === "env"
                                  ? "•••••••• (loaded from env)"
                                  : status?.secret_source === "override"
                                    ? "•••••••• (saved)"
                                    : "Enter client secret"
                              }
                              autoComplete="off"
                            />
                          </LabelWrapper>

                          <div className="flex flex-wrap items-center gap-2 pt-1">
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled={
                                saveOAuthConfig.isPending ||
                                (!draft.client_id.trim() &&
                                  !draft.client_secret.trim())
                              }
                              onClick={() => {
                                saveOAuthConfig.mutate(
                                  {
                                    credentialKey: group.credentialKey,
                                    client_id:
                                      draft.client_id.trim() || undefined,
                                    client_secret:
                                      draft.client_secret.trim() || undefined,
                                  },
                                  {
                                    onSuccess: () => {
                                      setCredentialDrafts((prev) => ({
                                        ...prev,
                                        [group.credentialKey]: {
                                          client_id: "",
                                          client_secret: "",
                                        },
                                      }));
                                      toast.success(
                                        `Saved ${group.label} credentials`,
                                      );
                                    },
                                    onError: (err) =>
                                      toast.error(
                                        err instanceof Error
                                          ? err.message
                                          : "Failed to save credentials",
                                      ),
                                  },
                                );
                              }}
                            >
                              {saveOAuthConfig.isPending ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                "Save"
                              )}
                            </Button>

                            <Button
                              type="button"
                              size="sm"
                              variant="ghost"
                              disabled={
                                clearOAuthConfig.isPending ||
                                badgeStatus === "not-configured"
                              }
                              onClick={() => {
                                clearOAuthConfig.mutate(group.credentialKey, {
                                  onSuccess: () =>
                                    toast.success(
                                      `Cleared ${group.label} override`,
                                    ),
                                  onError: (err) =>
                                    toast.error(
                                      err instanceof Error
                                        ? err.message
                                        : "Failed to clear credentials",
                                    ),
                                });
                              }}
                            >
                              Clear override
                            </Button>

                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="ml-auto"
                              disabled={
                                testConnection.isPending ||
                                badgeStatus === "not-configured"
                              }
                              onClick={() => {
                                trackButton({
                                  CTA: "Test Connector OAuth Connection",
                                  elementId: `test-connection-${group.credentialKey}`,
                                  namespace: "settings",
                                });
                                testConnection.mutate({
                                  connector: {
                                    id: group.testConnectorType,
                                    name: group.label,
                                    description: "",
                                    icon: "",
                                    status: "not_connected",
                                    type: group.testConnectorType,
                                  },
                                  redirectUri: `${window.location.origin}/auth/callback`,
                                  purpose: "test",
                                });
                              }}
                            >
                              {testConnection.isPending ? (
                                <>
                                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                                  Testing…
                                </>
                              ) : (
                                "Test Connection"
                              )}
                            </Button>
                          </div>
                          {group.credentialKey === "microsoft_graph" && (
                            <p className="text-xs text-muted-foreground">
                              Test Connection runs a Microsoft OAuth consent
                              check using OneDrive&apos;s app registration — the
                              same credentials also apply to SharePoint.
                            </p>
                          )}
                        </div>
                      </AccordionContent>
                    </AccordionItem>
                  );
                })}
              </Accordion>
            )}

            {nonOAuthConnectors.length > 0 && (
              <ul className="space-y-4">
                {nonOAuthConnectors.map(renderSwitchRow)}
              </ul>
            )}

            <div className="flex justify-end pt-6">
              <Button
                onClick={() => {
                  trackButton({
                    CTA: "Save Connector Access",
                    elementId: "save-connector-access-button",
                    namespace: "settings",
                  });
                  updateAccess.mutate(accessForSave, {
                    onSuccess: () => setUserDraft(null),
                  });
                }}
                disabled={updateAccess.isPending || !isDirty}
                className="min-w-[120px]"
                size="sm"
                variant="outline"
              >
                {updateAccess.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Saving…
                  </>
                ) : (
                  "Save changes"
                )}
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
