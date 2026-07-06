"use client";

import { useAuth } from "@/contexts/auth-context";
import { useBrand } from "@/contexts/brand-context";
import {
  buildSettingsTabAccess,
  type SettingsTabAccessContext,
} from "@/lib/brand";

export interface UsePermissionsResult {
  /** All permission strings granted to the current user. */
  permissions: Set<string>;
  /** True if the user has every listed permission. */
  can: (perm: string) => boolean;
  /** True if the user has at least one of the listed permissions. */
  canAny: (perms: string[]) => boolean;
  /** True if the user has all of the listed permissions. */
  canAll: (perms: string[]) => boolean;
  /** Force a refetch from /api/users/me/permissions. */
  refresh: () => Promise<void>;
  /** True while the auth context is still resolving. */
  isLoading: boolean;
  /**
   * Whether the backend is enforcing RBAC. When false, the system
   * runs in pre-RBAC mode — components that render only when RBAC is
   * meaningful (Users & Roles, audit log, role pills) should hide.
   */
  rbacEnforced: boolean;
}

/**
 * Single source of truth for permission checks in the UI.
 *
 * Pulls from auth-context (which fetched /api/users/me/permissions on
 * sign-in). The backend is the authoritative gate; this hook only drives
 * UI affordances (hide tabs, disable buttons, etc).
 */
export function usePermissions(): UsePermissionsResult {
  const {
    permissions,
    can,
    isLoading,
    refreshPermissions,
    isNoAuthMode,
    rbacEnforced,
  } = useAuth();

  const canAny = (perms: string[]) => {
    if (isNoAuthMode) return true;
    return perms.some((p) => permissions.has(p));
  };

  const canAll = (perms: string[]) => {
    if (isNoAuthMode) return true;
    return perms.every((p) => permissions.has(p));
  };

  return {
    permissions,
    can,
    canAny,
    canAll,
    refresh: refreshPermissions,
    isLoading,
    rbacEnforced,
  };
}

/** Settings nav + tab guards — bundles auth, brand, and permissions. */
export function useSettingsTabAccess(): SettingsTabAccessContext {
  const {
    isNoAuthMode,
    isIbmAuthMode,
    cloudContext,
    permissions,
    rbacEnforced,
  } = useAuth();
  const { brand } = useBrand();
  return buildSettingsTabAccess({
    isIbmAuthMode,
    cloudContext,
    isNoAuthMode,
    rbacEnforced,
    permissions,
    brand,
  });
}
