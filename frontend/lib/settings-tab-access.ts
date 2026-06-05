/** Shared settings visibility (tabs + connector list) — used by nav, RSC guards, and connector UI. */

export type SettingsTabAccessContext = {
  isCloudBrand: boolean;
  isNoAuthMode: boolean;
  rbacEnforced: boolean;
  permissions: Set<string>;
};

/**
 * Whether a permission-gated settings tab is visible/accessible.
 * RBAC applies in SaaS (cloud brand) only; OSS shows all standard tabs.
 * Mirrors auth-context `can()` when RBAC is enforced on cloud brand.
 */
export function canShowRbacGatedSettingsTab(
  perm: string,
  {
    isCloudBrand,
    isNoAuthMode,
    rbacEnforced,
    permissions,
  }: SettingsTabAccessContext,
): boolean {
  if (!isCloudBrand) return true;
  if (isNoAuthMode || !rbacEnforced) return true;
  return permissions.has(perm);
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

/** Which connector types appear on the Connectors and Connectors Permission tabs. */
export function isConnectorVisibleInSettings(
  type: string,
  {
    isCloudBrand,
    isIbmAuthMode,
  }: { isCloudBrand: boolean; isIbmAuthMode: boolean },
): boolean {
  if (type === "ibm_cos" || type === "aws_s3") return isIbmAuthMode;
  if (isCloudBrand && type === "onedrive") return false;
  return true;
}
