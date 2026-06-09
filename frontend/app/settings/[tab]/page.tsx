import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { redirect } from "next/navigation";
import { getQueryClient } from "@/app/api/get-query-client";
import {
  buildSettingsTabAccess,
  canAccessConnectorAccessTab,
  canShowRbacGatedSettingsTab,
} from "@/lib/brand";
import { fetchFromBackend } from "@/lib/fetch-server";
import { AgentSettingsSection } from "../_components/agent-settings-section";
import { ApiKeysSection } from "../_components/api-keys-section";
import { ConnectorAccessSection } from "../_components/connector-access-section";
import { ConnectorsTab } from "../_components/connectors-tab";
import { IngestSettingsSection } from "../_components/ingest-settings-section";
import ModelProviders from "../_components/model-providers";

const VALID_TABS = [
  "connectors",
  "providers",
  "langflow",
  "api-keys",
  "connector-access",
] as const;

type Tab = (typeof VALID_TABS)[number];

async function getTabAuthContext() {
  const [authRes, meRes] = await Promise.allSettled([
    fetchFromBackend("auth/me"),
    fetchFromBackend("users/me"),
  ]);

  const authData =
    authRes.status === "fulfilled" && authRes.value.ok
      ? await authRes.value.json()
      : {};
  const meData =
    meRes.status === "fulfilled" && meRes.value.ok
      ? await meRes.value.json()
      : {};

  const permissions = new Set<string>(
    Array.isArray(meData.permissions) ? meData.permissions : [],
  );
  const rbacEnforced =
    typeof meData.rbac_enforced === "boolean" ? meData.rbac_enforced : true;
  const cloudContext =
    typeof meData.cloud_context === "boolean" ? meData.cloud_context : false;

  return {
    isNoAuthMode: Boolean(authData.no_auth_mode),
    isIbmAuthMode: Boolean(authData.ibm_auth_mode),
    isAuthenticated: Boolean(authData.authenticated),
    permissions,
    rbacEnforced,
    cloudContext,
  };
}

export default async function SettingsTabPage({
  params,
}: {
  params: Promise<{ tab: string }>;
}) {
  const { tab } = await params;

  if (!VALID_TABS.includes(tab as Tab)) {
    redirect("/settings/connectors");
  }

  const {
    isNoAuthMode,
    isIbmAuthMode,
    isAuthenticated,
    permissions,
    rbacEnforced,
    cloudContext,
  } = await getTabAuthContext();

  const tabAccess = buildSettingsTabAccess({
    isIbmAuthMode,
    cloudContext,
    isNoAuthMode,
    rbacEnforced,
    permissions,
    useClientBrandPolicy: false,
  });

  if (
    tab === "api-keys" &&
    (isIbmAuthMode || (!isAuthenticated && !isNoAuthMode))
  ) {
    redirect("/settings/connectors");
  }
  if (
    tab === "providers" &&
    !canShowRbacGatedSettingsTab("providers:write", tabAccess)
  ) {
    redirect("/settings/connectors");
  }
  if (tab === "connector-access" && !canAccessConnectorAccessTab(tabAccess)) {
    redirect("/settings/connectors");
  }
  if (
    tab === "langflow" &&
    !canShowRbacGatedSettingsTab("config:write", tabAccess)
  ) {
    redirect("/settings/connectors");
  }

  const queryClient = getQueryClient();
  try {
    await queryClient.prefetchQuery({
      queryKey: ["settings"],
      queryFn: async () => {
        const res = await fetchFromBackend("settings");
        if (!res.ok) throw new Error("Failed to fetch settings");
        return res.json();
      },
    });
  } catch {
    // Backend unavailable — client handles loading normally
  }

  if (tab === "api-keys") {
    try {
      await queryClient.prefetchQuery({
        queryKey: ["api-keys"],
        queryFn: async () => {
          const res = await fetchFromBackend("keys");
          if (!res.ok) throw new Error("Failed to fetch api keys");
          return res.json();
        },
      });
    } catch {
      // Backend unavailable — client handles loading normally
    }
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      {tab === "connectors" && <ConnectorsTab />}
      {tab === "providers" && <ModelProviders />}
      {tab === "langflow" && (
        <div className="space-y-6">
          <AgentSettingsSection />
          <IngestSettingsSection />
        </div>
      )}
      {tab === "api-keys" && <ApiKeysSection />}
      {tab === "connector-access" && <ConnectorAccessSection />}
    </HydrationBoundary>
  );
}
