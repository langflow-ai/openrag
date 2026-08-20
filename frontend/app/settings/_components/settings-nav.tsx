"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/settings-tabs";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { useSettingsTabAccess } from "@/hooks/use-permissions";
import {
  canAccessConnectorAccessTab,
  canShowRbacGatedSettingsTab,
} from "@/lib/brand";
import { cn } from "@/lib/utils";

const TABS = [
  { value: "connectors", label: "Connectors" },
  { value: "providers", label: "Providers", perm: "providers:write" },
  // Agent settings write workspace config (admin-only).
  { value: "langflow", label: "Langflow", perm: "config:write" },
  // Knowledge ingest settings write workspace config (admin-only).
  // Preview controls on this tab stay gated by isIngestPreviewEnabled.
  { value: "ingestion", label: "Ingestion", perm: "config:write" },
  { value: "api-keys", label: "API Keys", apiKeysTab: true },
  {
    value: "connector-access",
    label: "Connector Settings",
    perm: "connectors:manage:access",
  },
] as const;

export function SettingsNav() {
  const pathname = usePathname();
  const { isAuthenticated, isNoAuthMode, isIbmAuthMode } = useAuth();
  const isCloudBrand = useIsCloudBrand();
  const tabAccess = useSettingsTabAccess();

  const currentTab = pathname.split("/").pop() ?? "connectors";

  const visibleTabs = TABS.filter((tab) => {
    if (tab.value === "connector-access") {
      return canAccessConnectorAccessTab(tabAccess);
    }
    if ("perm" in tab) return canShowRbacGatedSettingsTab(tab.perm, tabAccess);
    if ("apiKeysTab" in tab)
      return (isAuthenticated || isNoAuthMode) && !isIbmAuthMode;
    return true;
  });

  return (
    <Tabs value={currentTab}>
      <TabsList
        variant={isCloudBrand ? "line" : "default"}
        className={cn(!isCloudBrand && "mb-6 p-2 rounded-full")}
      >
        {visibleTabs.map((tab) => (
          <TabsTrigger
            key={tab.value}
            value={tab.value}
            asChild
            className={cn(!isCloudBrand && "p-3 rounded-full")}
          >
            <Link href={`/settings/${tab.value}`}>{tab.label}</Link>
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
