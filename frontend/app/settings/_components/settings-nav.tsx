"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/settings-tabs";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { usePermissions } from "@/hooks/use-permissions";
import {
  canAccessConnectorAccessTab,
  canShowRbacGatedSettingsTab,
} from "@/lib/settings-tab-access";
import { cn } from "@/lib/utils";

const TABS = [
  { value: "connectors", label: "Connectors" },
  { value: "providers", label: "Providers", perm: "providers:write" },
  // Agent + ingest settings write workspace config (admin-only).
  { value: "langflow", label: "Langflow", perm: "config:write" },
  { value: "api-keys", label: "API Keys", apiKeysTab: true },
  {
    value: "connector-access",
    label: "Connectors Permission",
    perm: "connectors:manage:access",
    connectorAccessTab: true,
  },
] as const;

export function SettingsNav() {
  const isCloudBrand = useIsCloudBrand();
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, isNoAuthMode, isIbmAuthMode } = useAuth();
  const {
    permissions,
    rbacEnforced,
    isLoading: permissionsLoading,
  } = usePermissions();

  const tabAccess = {
    isCloudBrand,
    isNoAuthMode,
    rbacEnforced,
    permissions,
  };

  /** RBAC-gated settings tabs apply in SaaS (cloud brand) only; OSS shows all tabs. */
  const canShowPermTab = (perm: string) => {
    if (permissionsLoading) return true;
    return canShowRbacGatedSettingsTab(perm, tabAccess);
  };

  const currentTab = pathname.split("/").pop() ?? "connectors";

  const visibleTabs = TABS.filter((tab) => {
    if ("connectorAccessTab" in tab)
      return isCloudBrand && canShowPermTab(tab.perm);
    if ("perm" in tab) return canShowPermTab(tab.perm);
    if ("apiKeysTab" in tab)
      return (isAuthenticated || isNoAuthMode) && !isIbmAuthMode;
    return true;
  });

  useEffect(() => {
    if (permissionsLoading) return;
    if (
      currentTab === "connector-access" &&
      !canAccessConnectorAccessTab(tabAccess)
    ) {
      router.replace("/settings/connectors");
    }
  }, [
    currentTab,
    permissionsLoading,
    isCloudBrand,
    isNoAuthMode,
    rbacEnforced,
    permissions,
    router,
  ]);

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
