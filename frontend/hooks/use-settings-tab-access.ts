"use client";

import { useMemo } from "react";
import { useAuth } from "@/contexts/auth-context";
import { useBrand, useIsCloudBrand } from "@/contexts/brand-context";
import { usePermissions } from "@/hooks/use-permissions";
import {
  buildSettingsTabAccess,
  type ConnectorSettingsVisibility,
  canAccessConnectorAccessTab,
  canShowRbacGatedSettingsTab,
} from "@/lib/settings-tab-access";

export function useConnectorSettingsVisibility(): ConnectorSettingsVisibility {
  const isCloudBrand = useIsCloudBrand();
  const { isIbmAuthMode } = useAuth();
  return useMemo(
    () => ({ isCloudBrand, isIbmAuthMode }),
    [isCloudBrand, isIbmAuthMode],
  );
}

export function useSettingsTabAccess() {
  const isCloudBrand = useIsCloudBrand();
  const { brand } = useBrand();
  const { isNoAuthMode, isIbmAuthMode } = useAuth();
  const {
    permissions,
    rbacEnforced,
    isLoading: permissionsLoading,
  } = usePermissions();

  const tabAccess = buildSettingsTabAccess({
    isIbmAuthMode,
    brand,
    isNoAuthMode,
    rbacEnforced,
    permissions,
  });

  const canShowPermTab = (perm: string) => {
    if (permissionsLoading) return true;
    return canShowRbacGatedSettingsTab(perm, tabAccess);
  };

  const canShowConnectorAccessTab = () => {
    if (permissionsLoading) return true;
    return canAccessConnectorAccessTab(tabAccess);
  };

  return {
    tabAccess,
    isCloudBrand,
    permissionsLoading,
    canShowPermTab,
    canShowConnectorAccessTab,
  };
}
