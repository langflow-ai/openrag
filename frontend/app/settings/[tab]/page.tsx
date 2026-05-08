import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { redirect } from "next/navigation";
import { getQueryClient } from "@/app/api/get-query-client";
import { fetchFromBackend } from "@/lib/fetch-server";
import { AgentSettingsSection } from "../_components/agent-settings-section";
import { ApiKeysSection } from "../_components/api-keys-section";
import { ConnectorsTab } from "../_components/connectors-tab";
import { IngestSettingsSection } from "../_components/ingest-settings-section";
import ModelProviders from "../_components/model-providers";
import { UsersAndRolesSection } from "../_components/users-and-roles-section";

const VALID_TABS = [
  "connectors",
  "providers",
  "langflow",
  "api-keys",
  "roles",
] as const;

type Tab = (typeof VALID_TABS)[number];

export default async function SettingsTabPage({
  params,
}: {
  params: Promise<{ tab: string }>;
}) {
  const { tab } = await params;

  if (!VALID_TABS.includes(tab as Tab)) {
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
    if (tab === "api-keys") {
      await queryClient.prefetchQuery({
        queryKey: ["api-keys"],
        queryFn: async () => {
          const res = await fetchFromBackend("keys");
          if (!res.ok) throw new Error("Failed to fetch api keys");
          return res.json();
        },
      });
    }
  } catch {
    // Backend unavailable — client handles loading normally
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
      {tab === "roles" && <UsersAndRolesSection />}
    </HydrationBoundary>
  );
}
