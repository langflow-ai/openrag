/** Brand preference, SaaS policy context, and settings tab visibility. */

export type Brand = "oss" | "ibm";

export const IBM_THEME_DEV = process.env.NEXT_PUBLIC_IBM_THEME_DEV === "true";

/** Default when no localStorage — must match `BrandProvider` initial state. */
export const DEFAULT_BRAND: Brand = IBM_THEME_DEV ? "ibm" : "oss";

/** Normalize stored brand value; unknown/missing uses `DEFAULT_BRAND`. */
export function resolveBrand(brand: Brand | string | undefined): Brand {
  if (brand === "ibm" || brand === "oss") return brand;
  return DEFAULT_BRAND;
}

/** IBM/SaaS UI styling from context brand only (see `BrandProvider`). */
export function isCloudBrand(brand: Brand | string | undefined): boolean {
  if (!IBM_THEME_DEV) return resolveBrand(brand) === "ibm";
  return resolveBrand(brand) !== "oss";
}

/**
 * SaaS policy context (connector access tab, RBAC-gated settings).
 * Production: IBM auth or backend `cloud_context`.
 * Local: IBM theme dev + IBM brand mirrors SaaS settings UX (client brand only).
 */
export function isSaasPolicyContext({
  isIbmAuthMode,
  cloudContext = false,
  brand,
  /** RSC cannot read localStorage — skip dev brand toggle on server guards. */
  skipDevBrand = false,
}: {
  isIbmAuthMode: boolean;
  cloudContext?: boolean;
  brand?: Brand | string | undefined;
  skipDevBrand?: boolean;
}): boolean {
  if (isIbmAuthMode || cloudContext) return true;
  if (!IBM_THEME_DEV) return false;
  // RSC cannot read localStorage — mirror BrandProvider's default brand.
  const effectiveBrand = skipDevBrand ? DEFAULT_BRAND : resolveBrand(brand);
  return effectiveBrand !== "oss";
}

/** False when the admin explicitly disabled this connector for the workspace. */
export function isConnectorAllowedByWorkspace(
  type: string,
  storedAccess: Record<string, boolean>,
): boolean {
  return storedAccess[type] !== false;
}

/**
 * Connectors tab visibility: workspace policy first, then deployment rules.
 * Explicit `storedAccess[type] === true` overrides deployment filters except
 * OneDrive outside OSS brand (hidden in SaaS/cloud UI).
 */
export function isConnectorShownInWorkspace(
  type: string,
  storedAccess: Record<string, boolean>,
  {
    isCloudBrand: cloudBrand,
    isIbmAuthMode,
  }: { isCloudBrand: boolean; isIbmAuthMode: boolean },
): boolean {
  if (!isConnectorAllowedByWorkspace(type, storedAccess)) return false;
  if (storedAccess[type] === true && !(type === "onedrive" && cloudBrand)) {
    return true;
  }
  return isConnectorTypeVisible(type, {
    isCloudBrand: cloudBrand,
    isIbmAuthMode,
  });
}

/** Deployment filter shared by Connectors tab, permission admin, and upload menus. */
export function isConnectorTypeVisible(
  type: string,
  {
    isCloudBrand: cloudBrand,
    isIbmAuthMode,
  }: { isCloudBrand: boolean; isIbmAuthMode: boolean },
): boolean {
  if (type === "ibm_cos" || type === "aws_s3") return isIbmAuthMode;
  if (cloudBrand && type === "onedrive") return false;
  return true;
}

// --- Settings tab access (nav, RSC guards, auth-context `can()`) ---

export type SettingsTabAccessContext = {
  isSaasPolicy: boolean;
  isNoAuthMode: boolean;
  rbacEnforced: boolean;
  permissions: Set<string>;
};

export function buildSettingsTabAccess({
  isIbmAuthMode,
  cloudContext,
  isNoAuthMode,
  permissions,
  rbacEnforced,
  brand = DEFAULT_BRAND,
  useClientBrandPolicy = true,
}: {
  isIbmAuthMode: boolean;
  cloudContext: boolean;
  isNoAuthMode: boolean;
  permissions: Set<string>;
  rbacEnforced: boolean;
  brand?: Brand | string;
  /** False on RSC tab guards — brand lives in localStorage, not on the server. */
  useClientBrandPolicy?: boolean;
}): SettingsTabAccessContext {
  return {
    isSaasPolicy: isSaasPolicyContext({
      isIbmAuthMode,
      cloudContext,
      brand,
      skipDevBrand: !useClientBrandPolicy,
    }),
    isNoAuthMode,
    rbacEnforced,
    permissions,
  };
}

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

/** RBAC applies in SaaS policy context only; OSS shows all standard tabs. */
export function canShowRbacGatedSettingsTab(
  perm: string,
  ctx: SettingsTabAccessContext,
): boolean {
  if (!ctx.isSaasPolicy) return true;
  return hasRbacPermission(perm, ctx);
}

export function canAccessConnectorAccessTab(
  ctx: SettingsTabAccessContext,
): boolean {
  return ctx.isSaasPolicy && hasRbacPermission("connectors:manage:access", ctx);
}
