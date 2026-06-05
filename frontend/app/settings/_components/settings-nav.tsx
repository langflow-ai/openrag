"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/settings-tabs";
import { useAuth } from "@/contexts/auth-context";
import { useBrand, useIsCloudBrand } from "@/contexts/brand-context";
import { usePermissions } from "@/hooks/use-permissions";
import {
  buildSettingsTabAccess,
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
  },
] as const;

export function SettingsNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, isNoAuthMode, isIbmAuthMode } = useAuth();
  const { brand } = useBrand();
  const isCloudBrand = useIsCloudBrand();
  const { permissions, rbacEnforced } = usePermissions();
  const tabAccess = buildSettingsTabAccess({
    isIbmAuthMode,
    brand,
    isNoAuthMode,
    rbacEnforced,
    permissions,
  });

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

  const tabIsVisible = visibleTabs.some((tab) => tab.value === currentTab);
  const fallbackTab = visibleTabs[0]?.value ?? "connectors";

  useEffect(() => {
    if (visibleTabs.length === 0 || tabIsVisible) return;
    router.replace(`/settings/${fallbackTab}`);
    router.refresh();
  }, [tabIsVisible, fallbackTab, visibleTabs.length, router]);

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
