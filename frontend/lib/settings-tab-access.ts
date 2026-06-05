import { type Brand, isCloudBrand } from "@/lib/brand";

/** Shared settings visibility — used by nav, RSC guards, and auth-context `can()`. */

export type SettingsTabAccessContext = {
  isCloudBrand: boolean;
  isNoAuthMode: boolean;
  rbacEnforced: boolean;
  permissions: Set<string>;
};

export function buildSettingsTabAccess({
  isIbmAuthMode,
  brand,
  isNoAuthMode,
  permissions,
  rbacEnforced,
}: {
  isIbmAuthMode: boolean;
  brand: Brand | string | undefined;
  isNoAuthMode: boolean;
  permissions: Set<string>;
  rbacEnforced: boolean;
}): SettingsTabAccessContext {
  return {
    isCloudBrand: isCloudBrand({ isIbmAuthMode, brand }),
    isNoAuthMode,
    rbacEnforced,
    permissions,
  };
}

/** Core RBAC check — also used by auth-context `can()`. */
export function hasRbacPermission(
  perm: string,
  {
    isNoAuthMode,
    rbacEnforced,
    permissions,
  }: Pick<
    SettingsTabAccessContext,
    "isNoAuthMode" | "rbacEnforced" | "permissions"
  >,
): boolean {
  if (isNoAuthMode || !rbacEnforced) return true;
  return permissions.has(perm);
}

/**
 * Whether a permission-gated settings tab is visible/accessible.
 * RBAC applies in SaaS (cloud brand) only; OSS shows all standard tabs.
 */
export function canShowRbacGatedSettingsTab(
  perm: string,
  ctx: SettingsTabAccessContext,
): boolean {
  if (!ctx.isCloudBrand) return true;
  return hasRbacPermission(perm, ctx);
}

/** Connectors Permission is cloud-only plus the shared SaaS RBAC gate. */
export function canAccessConnectorAccessTab(
  ctx: SettingsTabAccessContext,
): boolean {
  return (
    ctx.isCloudBrand &&
    canShowRbacGatedSettingsTab("connectors:manage:access", ctx)
  );
}
