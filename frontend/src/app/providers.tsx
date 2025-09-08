"use client";
import { QueryClientProvider } from "@tanstack/react-query";
import { getQueryClient } from "@/app/api/get-query-client";
import type * as React from "react";

export default function Providers({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient();

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
