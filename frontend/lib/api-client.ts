import axios, { type AxiosResponse } from "axios";
import {
  frontendApiBasePath,
  withFrontendBasePath,
} from "./frontend-base-path";

/**
 * Same-origin client for browser calls to Next's catch-all API proxy.
 *
 * The base URL includes Next's build-time basePath, so `apiClient.get("/tasks")`
 * reaches `/openrag-fe/api/tasks` when the app is mounted at `/openrag-fe`.
 */
export const apiClient = axios.create({
  baseURL: frontendApiBasePath,
  withCredentials: true,
  // Existing callers have several legitimate non-2xx status branches. Keep
  // those explicit rather than turning them into Axios rejections.
  validateStatus: () => true,
});

function redirectForUnauthorized(response: AxiosResponse<unknown>) {
  if (typeof window === "undefined" || response.status !== 401) return;

  const payload = response.data;
  if (!payload || typeof payload !== "object") return;

  const redirectUrl =
    (payload as Record<string, unknown>).redirect_url ||
    (payload as Record<string, unknown>).redirectUrl ||
    (payload as Record<string, unknown>).redirect;
  if (typeof redirectUrl !== "string") return;

  // Redirect only to an application-local path or same-origin absolute URL.
  if (redirectUrl.startsWith("/") && !redirectUrl.startsWith("//")) {
    window.location.href = withFrontendBasePath(redirectUrl);
    return;
  }

  try {
    const url = new URL(redirectUrl, window.location.origin);
    if (url.origin === window.location.origin) {
      url.pathname = withFrontendBasePath(url.pathname);
      window.location.href = url.toString();
    }
  } catch {
    // Malformed redirect URLs are ignored rather than becoming open redirects.
  }
}

apiClient.interceptors.response.use((response) => {
  redirectForUnauthorized(response);
  return response;
});
