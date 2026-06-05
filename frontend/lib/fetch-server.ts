import { cookies } from "next/headers";
import { BRAND_COOKIE, resolveBrand } from "@/lib/brand";

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
  const brand = resolveBrand(cookieStore.get(BRAND_COOKIE)?.value);

  return fetch(`${baseUrl}/${path}`, {
    ...init,
    headers: {
      ...init?.headers,
      Cookie: cookieStore.toString(),
      "X-OpenRAG-Brand": brand,
    },
    cache: "no-store",
  });
}
