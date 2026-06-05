"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/settings-tabs";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { usePermissions } from "@/hooks/use-permissions";
import { cn } from "@/lib/utils";

const TABS = [
  { value: "connectors", label: "Connectors" },
  { value: "providers", label: "Providers", perm: "providers:write" },
  // Agent + ingest settings write workspace config (admin-only).
  { value: "langflow", label: "Langflow", perm: "config:write" },
  { value: "api-keys", label: "API Keys", apiKeysTab: true },
  {
    value: "connector-access",
    label: "Connector access",
    perm: "connectors:manage:access",
    connectorAccessTab: true,
  },
] as const;

export function SettingsNav() {
  const isCloudBrand = useIsCloudBrand();
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, isNoAuthMode, isIbmAuthMode } = useAuth();
  const { can } = usePermissions();
  const canManageConnectorAccess = can("connectors:manage:access");

  const currentTab = pathname.split("/").pop() ?? "connectors";

  const visibleTabs = TABS.filter((tab) => {
    if ("connectorAccessTab" in tab)
      return isCloudBrand && canManageConnectorAccess;
    if ("perm" in tab) return can(tab.perm);
    if ("apiKeysTab" in tab)
      return (isAuthenticated || isNoAuthMode) && !isIbmAuthMode;
    return true;
  });

  useEffect(() => {
    if (
      currentTab === "connector-access" &&
      !(isCloudBrand && canManageConnectorAccess)
    ) {
      router.replace("/settings/connectors");
    }
  }, [currentTab, isCloudBrand, canManageConnectorAccess, router]);

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
            onClick={() => router.push(`/settings/${tab.value}`)}
            className={cn(!isCloudBrand && "p-3 rounded-full")}
          >
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
