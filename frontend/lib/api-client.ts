import axios, { type AxiosResponse } from "axios";
import {
  frontendApiBasePath,
  withFrontendBasePath,
} from "./frontend-base-path";

const runtimeApiBasePath =
  typeof window === "undefined"
    ? frontendApiBasePath
    : new URL(frontendApiBasePath, window.location.origin).toString();

/**
 * Same-origin client for browser calls to Next's catch-all API proxy.
 *
 * The base URL includes Next's build-time basePath, so `apiClient.get("/tasks")`
 * reaches `/openrag-fe/api/tasks` when the app is mounted at `/openrag-fe`.
 */
export const apiClient = axios.create({
  baseURL: runtimeApiBasePath,
  withCredentials: true,
  // Existing callers have several legitimate non-2xx status branches. Keep
  // those explicit rather than turning them into Axios rejections.
  validateStatus: () => true,
});

export function getUnauthorizedRedirectUrl(redirectUrl: unknown): string {
  const fallback = withFrontendBasePath("/login");
  if (typeof redirectUrl !== "string") return fallback;

  try {
    if (typeof window === "undefined") return fallback;
    const url = new URL(redirectUrl, window.location.origin);
    if (url.origin !== window.location.origin) return fallback;

    url.pathname = withFrontendBasePath(url.pathname);
    // Keep relative application paths relative, while preserving absolute
    // same-origin candidates returned by the backend.
    if (redirectUrl.startsWith("/") && !redirectUrl.startsWith("//")) {
      return `${url.pathname}${url.search}${url.hash}`;
    }
    return url.toString();
  } catch {
    // Malformed redirect URLs fall back to the local login page.
  }

  // Cross-origin redirect URLs are rejected to prevent open redirects, but a
  // local login fallback still gives the user a way to recover from a 401.
  return fallback;
}

function redirectForUnauthorized(response: AxiosResponse<unknown>) {
  if (typeof window === "undefined" || response.status !== 401) return;

  const payload = response.data;
  if (!payload || typeof payload !== "object") return;

  const redirectUrl =
    (payload as Record<string, unknown>).redirect_url ||
    (payload as Record<string, unknown>).redirectUrl ||
    (payload as Record<string, unknown>).redirect;
  if (typeof redirectUrl !== "string" || !redirectUrl) return;

  window.location.href = getUnauthorizedRedirectUrl(redirectUrl);
}

apiClient.interceptors.response.use((response) => {
  redirectForUnauthorized(response);
  return response;
});
