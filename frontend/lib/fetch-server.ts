import { cookies } from "next/headers";

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

  return fetch(`${baseUrl}/${path}`, {
    ...init,
    headers: {
      ...init?.headers,
      Cookie: cookieStore.toString(),
    },
    cache: "no-store",
  });
}
