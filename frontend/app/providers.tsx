"use client";
import { QueryClientProvider } from "@tanstack/react-query";
import type * as React from "react";
import { getQueryClient } from "@/app/api/get-query-client";

if (typeof window !== "undefined") {
  const originalFetch = window.fetch;
  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    if (response.status === 401) {
      try {
        const clone = response.clone();
        const data = await clone.json();
        if (data && typeof data === "object") {
          const redirectUrl =
            data.redirect_url || data.redirectUrl || data.redirect;
          if (redirectUrl && typeof redirectUrl === "string") {
            window.location.href = redirectUrl;
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
}

export default function Providers({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient();

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
