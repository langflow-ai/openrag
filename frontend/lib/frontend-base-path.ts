/**
 * Return the path prefix under which Next serves the frontend.
 *
 * Next requires `basePath` values to be known at build time. Keep the
 * normalization shared between next.config.ts and browser API requests so a
 * deployment cannot put pages under one prefix and API calls under another.
 */
export function normalizeFrontendBasePath(value?: string): string {
  const trimmed = value?.trim();
  if (!trimmed || trimmed === "/") return "";

  const prefixed = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  const normalized = prefixed.replace(/\/+$/, "");

  if (
    !normalized ||
    normalized.includes("?") ||
    normalized.includes("#") ||
    normalized.includes("://")
  ) {
    throw new Error(
      "OPENRAG_FRONTEND_BASE_PATH must be a path such as /openrag-fe",
    );
  }

  return normalized;
}

export const frontendBasePath = normalizeFrontendBasePath(
  process.env.NEXT_PUBLIC_OPENRAG_FRONTEND_BASE_PATH,
);

export const frontendApiBasePath = `${frontendBasePath}/api`;

/** Prefix an application-local path without changing external URLs. */
export function withFrontendBasePath(path: string): string {
  if (!frontendBasePath || !path.startsWith("/")) return path;
  if (path === frontendBasePath || path.startsWith(`${frontendBasePath}/`)) {
    return path;
  }
  return `${frontendBasePath}${path}`;
}

/** Build an absolute same-origin URL for OAuth callbacks and redirects. */
export function frontendUrl(
  path: string,
  origin = window.location.origin,
): string {
  return new URL(withFrontendBasePath(path), origin).toString();
}
