import { cookies } from "next/headers";
import { BRAND_COOKIE } from "@/lib/brand";

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
  const brandCookie = cookieStore.get(BRAND_COOKIE)?.value;
  const brandHeader =
    brandCookie === "oss" || brandCookie === "ibm" ? brandCookie : undefined;

  return fetch(`${baseUrl}/${path}`, {
    ...init,
    headers: {
      ...init?.headers,
      Cookie: cookieStore.toString(),
      ...(brandHeader ? { "X-OpenRAG-Brand": brandHeader } : {}),
    },
    cache: "no-store",
  });
}
