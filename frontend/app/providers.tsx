"use client";
import { QueryClientProvider } from "@tanstack/react-query";
import type * as React from "react";
import { getQueryClient } from "@/app/api/get-query-client";

if (typeof window !== "undefined") {
  const FETCH_PATCHED = Symbol.for("__fetch_patched__");
  if (!(window.fetch as any)[FETCH_PATCHED]) {
    const originalFetch = window.fetch;
    const patchedFetch = async (...args: Parameters<typeof fetch>) => {
      const response = await originalFetch(...args);
      if (response.status === 401) {
        try {
          const clone = response.clone();
          const data = await clone.json();
          if (data && typeof data === "object") {
            const redirectUrl =
              data.redirect_url || data.redirectUrl || data.redirect;
            if (redirectUrl && typeof redirectUrl === "string") {
              // Validate redirectUrl to prevent open redirect
              let validatedUrl = "/login";
              if (
                redirectUrl.startsWith("/") &&
                !redirectUrl.startsWith("//")
              ) {
                // Relative path - safe to use
                validatedUrl = redirectUrl;
              } else {
                try {
                  const url = new URL(redirectUrl, location.origin);
                  if (url.origin === location.origin) {
                    // Same-origin absolute URL - safe to use
                    validatedUrl = redirectUrl;
                  }
                } catch (_e) {
                  // Invalid URL, use default
                }
              }
              window.location.href = validatedUrl;
            }
          }
        } catch (e) {
          console.error(
            "Failed to parse 401 response payload for redirect url:",
            e,
          );
        }
      }
      return response;
    };
    (patchedFetch as any)[FETCH_PATCHED] = true;
    window.fetch = patchedFetch as typeof fetch;
  }
}

export default function Providers({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient();

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
