"use client";
import { QueryClientProvider } from "@tanstack/react-query";
import type * as React from "react";
import { getQueryClient } from "@/app/api/get-query-client";
import { withFrontendBasePath } from "@/lib/frontend-base-path";

if (typeof window !== "undefined") {
  const FETCH_PATCHED = Symbol.for("__fetch_patched__");
  type MarkedFetch = typeof window.fetch & {
    [FETCH_PATCHED]?: boolean;
  };
  const currentFetch = window.fetch as MarkedFetch;

  if (!currentFetch[FETCH_PATCHED]) {
    const originalFetch = window.fetch.bind(window);
    const patchedFetch: typeof window.fetch = async (input, init) => {
      let rewrittenInput = input;
      const rawUrl =
        input instanceof Request
          ? input.url
          : typeof input === "string" || input instanceof URL
            ? input.toString()
            : undefined;

      if (rawUrl) {
        try {
          const url = new URL(rawUrl, window.location.origin);
          if (
            url.origin === window.location.origin &&
            url.pathname.startsWith("/api/")
          ) {
            url.pathname = withFrontendBasePath(url.pathname);
            const rewrittenUrl = `${url.pathname}${url.search}${url.hash}`;
            rewrittenInput =
              input instanceof Request
                ? new Request(url.toString(), input)
                : input instanceof URL
                  ? url
                  : input.startsWith("/")
                    ? rewrittenUrl
                    : url.toString();
          }
        } catch {
          // Preserve the original request for malformed URLs.
        }
      }

      const response = await originalFetch(rewrittenInput, init);
      if (response.status === 401) {
        try {
          const clone = response.clone();
          const data = await clone.json();
          if (data && typeof data === "object") {
            const redirectUrl =
              data.redirect_url || data.redirectUrl || data.redirect;
            if (redirectUrl && typeof redirectUrl === "string") {
              let validatedUrl = withFrontendBasePath("/login");
              if (
                redirectUrl.startsWith("/") &&
                !redirectUrl.startsWith("//")
              ) {
                validatedUrl = withFrontendBasePath(redirectUrl);
              } else {
                try {
                  const url = new URL(redirectUrl, location.origin);
                  if (url.origin === location.origin) {
                    url.pathname = withFrontendBasePath(url.pathname);
                    validatedUrl = url.toString();
                  }
                } catch {
                  // Invalid URLs use the local login fallback.
                }
              }
              window.location.href = validatedUrl;
            }
          }
        } catch (error) {
          console.error(
            "Failed to parse 401 response payload for redirect url:",
            error,
          );
        }
      }
      return response;
    };

    (patchedFetch as MarkedFetch)[FETCH_PATCHED] = true;
    window.fetch = patchedFetch;
  }
}

export default function Providers({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient();

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
