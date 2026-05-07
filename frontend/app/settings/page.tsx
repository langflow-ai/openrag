import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getQueryClient } from "@/app/api/get-query-client";
import { fetchFromBackend } from "@/lib/fetch-server";
import SettingsClient from "./settings-client";

export default async function SettingsPage() {
  const queryClient = getQueryClient();

  try {
    await Promise.all([
      queryClient.prefetchQuery({
        queryKey: ["settings"],
        queryFn: async () => {
          const res = await fetchFromBackend("settings");
          if (!res.ok) throw new Error("Failed to fetch settings");
          return res.json();
        },
      }),
      queryClient.prefetchQuery({
        queryKey: ["api-keys"],
        queryFn: async () => {
          const res = await fetchFromBackend("keys");
          if (!res.ok) throw new Error("Failed to fetch api keys");
          return res.json();
        },
      }),
    ]);
  } catch {
    // Backend unavailable or unauthenticated — client handles loading/auth normally
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <SettingsClient />
    </HydrationBoundary>
  );
}
