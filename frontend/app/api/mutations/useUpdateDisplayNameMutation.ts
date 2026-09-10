import { useMutation } from "@tanstack/react-query";

interface UpdateDisplayNameVariables {
  display_name: string | null;
}

export function useUpdateDisplayNameMutation() {
  return useMutation({
    mutationFn: async ({ display_name }: UpdateDisplayNameVariables) => {
      const response = await fetch("/api/users/me/display-name", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name }),
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(
          (err as { detail?: string }).detail ?? "Failed to save display name",
        );
      }
      return response.json() as Promise<{ display_name: string | null }>;
    },
  });
}
