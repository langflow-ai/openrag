import { cookies, headers } from "next/headers";

export async function fetchFromBackend(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const backendHost = process.env.OPENRAG_BACKEND_HOST || "localhost";
  const backendSSL = process.env.OPENRAG_BACKEND_SSL === "true";
  const baseUrl = backendSSL
    ? `https://${backendHost}:8000`
    : `http://${backendHost}:8000`;

  const cookieStore = await cookies();
  const incoming = await headers();

  // Forward the gateway-injected auth headers, not just the cookie. In RBAC
  // mode (OPENRAG_RBAC_ENFORCE=true) the backend derives identity/permissions
  // from the JWT in the Authorization header and ignores the session cookie
  // (src/dependencies.py). The browser proxy (app/api/[...path]/route.ts)
  // already forwards these; server components must too, or server-rendered
  // permission checks (e.g. settings/[tab]/page.tsx) see no permissions and
  // wrongly redirect. Header names honor the backend's env overrides.
  const jwtAuthHeader = (
    process.env.OPENRAG_JWT_AUTH_HEADER || "Authorization"
  ).toLowerCase();
  const ibmCredentialsHeader = (
    process.env.IBM_CREDENTIALS_HEADER || "X-IBM-LH-Credentials"
  ).toLowerCase();

  const forwarded: Record<string, string> = {
    Cookie: cookieStore.toString(),
  };
  const authValue = incoming.get(jwtAuthHeader);
  if (authValue) forwarded[jwtAuthHeader] = authValue;
  const credentialsValue = incoming.get(ibmCredentialsHeader);
  if (credentialsValue) forwarded[ibmCredentialsHeader] = credentialsValue;

  return fetch(`${baseUrl}/${path}`, {
    ...init,
    headers: {
      ...forwarded,
      ...init?.headers,
    },
    cache: "no-store",
  });
}
