/** Shared brand preference — cookie is readable in RSC; localStorage is client-only. */

export type Brand = "oss" | "ibm";

export const BRAND_COOKIE = "openrag-brand";

export const IBM_THEME_DEV = process.env.NEXT_PUBLIC_IBM_THEME_DEV === "true";

/** Keep in sync with `useIsCloudBrand()` in brand-context. */
export function isCloudBrand({
  isIbmAuthMode,
  brand,
}: {
  isIbmAuthMode: boolean;
  brand: Brand | string | undefined;
}): boolean {
  if (isIbmAuthMode) return true;
  if (!IBM_THEME_DEV) return false;
  // Dev tooling: only IBM theme exposes SaaS-only settings (e.g. roles tab).
  return brand !== "oss";
}
