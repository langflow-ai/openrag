import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import axios from "axios";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { getQueryClient } from "@/app/api/get-query-client";
import {
  buildSettingsTabAccess,
  canAccessConnectorAccessTab,
  canShowRbacGatedSettingsTab,
} from "@/lib/brand";
import { AgentSettingsSection } from "../_components/agent-settings-section";
import { ApiKeysSection } from "../_components/api-keys-section";
import { ConnectorAccessSection } from "../_components/connector-access-section";
import { ConnectorsTab } from "../_components/connectors-tab";
import { IngestionTab } from "../_components/ingestion-tab";
import ModelProviders from "../_components/model-providers";

const VALID_TABS = [
  "connectors",
  "providers",
  "ingestion",
  "agent",
  "api-keys",
  "connector-access",
] as const;

type Tab = (typeof VALID_TABS)[number];

function isValidTab(tab: string): tab is Tab {
  return (VALID_TABS as readonly string[]).includes(tab);
}

async function getTabAuthContext() {
  const backendHost = process.env.OPENRAG_BACKEND_HOST || "localhost";
  const backendSSL = process.env.OPENRAG_BACKEND_SSL === "true";
  const backendPort = process.env.OPENRAG_BACKEND_PORT || "8000";
  const backendBaseUrl = `${backendSSL ? "https" : "http"}://${backendHost}:${backendPort}`;
  const cookieStore = await cookies();
  const incoming = await headers();

  const jwtAuthHeader = (
    process.env.OPENRAG_JWT_AUTH_HEADER || "Authorization"
  ).toLowerCase();
  const ibmCredentialsHeader = (
    process.env.IBM_CREDENTIALS_HEADER || "X-IBM-LH-Credentials"
  ).toLowerCase();
  const forwardedHeaders: Record<string, string> = {
    Cookie: cookieStore.toString(),
  };
  const authValue = incoming.get(jwtAuthHeader);
  if (authValue) forwardedHeaders[jwtAuthHeader] = authValue;
  const credentialsValue = incoming.get(ibmCredentialsHeader);
  if (credentialsValue)
    forwardedHeaders[ibmCredentialsHeader] = credentialsValue;

  const requestConfig = {
    headers: forwardedHeaders,
    validateStatus: () => true,
  };
  const [authRes, meRes] = await Promise.allSettled([
    axios.get(`${backendBaseUrl}/auth/me`, requestConfig),
    axios.get(`${backendBaseUrl}/users/me`, requestConfig),
  ]);

  const authData =
    authRes.status === "fulfilled" &&
    authRes.value.status >= 200 &&
    authRes.value.status < 300
      ? authRes.value.data
      : {};
  const meData =
    meRes.status === "fulfilled" &&
    meRes.value.status >= 200 &&
    meRes.value.status < 300
      ? meRes.value.data
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
    backendBaseUrl,
    forwardedHeaders,
  };
}

export default async function SettingsTabPage({
  params,
}: {
  params: Promise<{ tab: string }>;
}) {
  const { tab } = await params;

  if (!isValidTab(tab)) {
    redirect("/settings/connectors");
  }

  const {
    isNoAuthMode,
    isIbmAuthMode,
    isAuthenticated,
    permissions,
    rbacEnforced,
    cloudContext,
    backendBaseUrl,
    forwardedHeaders,
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
    (tab === "agent" || tab === "ingestion") &&
    !canShowRbacGatedSettingsTab("config:write", tabAccess)
  ) {
    redirect("/settings/connectors");
  }

  const queryClient = getQueryClient();
  try {
    await queryClient.prefetchQuery({
      queryKey: ["settings"],
      queryFn: async () => {
        const res = await axios.get(`${backendBaseUrl}/settings`, {
          headers: forwardedHeaders,
          validateStatus: () => true,
        });
        if (res.status < 200 || res.status >= 300) {
          throw new Error("Failed to fetch settings");
        }
        return res.data;
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
          const res = await axios.get(`${backendBaseUrl}/keys`, {
            headers: forwardedHeaders,
            validateStatus: () => true,
          });
          if (res.status < 200 || res.status >= 300) {
            throw new Error("Failed to fetch api keys");
          }
          return res.data;
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
      {tab === "ingestion" && <IngestionTab />}
      {tab === "agent" && <AgentSettingsSection />}
      {tab === "api-keys" && <ApiKeysSection />}
      {tab === "connector-access" && <ConnectorAccessSection />}
    </HydrationBoundary>
  );
}
