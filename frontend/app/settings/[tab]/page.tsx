import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { redirect } from "next/navigation";
import { getQueryClient } from "@/app/api/get-query-client";
import { fetchFromBackend } from "@/lib/fetch-server";
import { AgentSettingsSection } from "../_components/agent-settings-section";
import { ApiKeysSection } from "../_components/api-keys-section";
import { ConnectorsTab } from "../_components/connectors-tab";
import { IngestSettingsSection } from "../_components/ingest-settings-section";
import ModelProviders from "../_components/model-providers";

const VALID_TABS = ["connectors", "providers", "langflow", "api-keys"] as const;

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

  return {
    isNoAuthMode: Boolean(authData.no_auth_mode),
    isIbmAuthMode: Boolean(authData.ibm_auth_mode),
    isAuthenticated: Boolean(authData.authenticated),
    permissions: new Set<string>(
      Array.isArray(meData.permissions) ? meData.permissions : [],
    ),
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

  const { isNoAuthMode, isIbmAuthMode, isAuthenticated, permissions } =
    await getTabAuthContext();

  // Mirror the visibility logic from settings-nav.tsx
  if (
    tab === "api-keys" &&
    (isIbmAuthMode || (!isAuthenticated && !isNoAuthMode))
  ) {
    redirect("/settings/connectors");
  }
  if (
    tab === "providers" &&
    !isNoAuthMode &&
    !permissions.has("providers:write")
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
    </HydrationBoundary>
  );
}
