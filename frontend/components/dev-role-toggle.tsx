"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";

const DEV_THEME =
  typeof process !== "undefined" &&
  process.env.NEXT_PUBLIC_IBM_THEME_DEV === "true";

function parseApiError(
  result: Record<string, unknown>,
  status: number,
): string {
  if (typeof result.error === "string") return result.error;
  const detail = result.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msg = detail
      .map((d) =>
        typeof d === "object" && d && "msg" in d ? String(d.msg) : "",
      )
      .filter(Boolean)
      .join("; ");
    if (msg) return msg;
  }
  return `Failed to set role (${status})`;
}

export function DevRoleToggle() {
  const isCloudBrand = useIsCloudBrand();
  const router = useRouter();
  const queryClient = useQueryClient();
  const {
    roles,
    isAuthenticated,
    isNoAuthMode,
    refreshPermissions,
    applyDevRoles,
  } = useAuth();
  const isAdmin = roles.includes("admin");
  const currentRole = isAdmin ? "admin" : "user";

  const mutation = useMutation({
    mutationFn: async (role: "admin" | "user") => {
      const response = await fetch("/api/users/me/dev-role", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
        credentials: "include",
      });
      if (!response.ok) {
        const result = (await response.json().catch(() => ({}))) as Record<
          string,
          unknown
        >;
        throw new Error(parseApiError(result, response.status));
      }
      return response.json() as Promise<{ roles?: string[]; role?: string }>;
    },
    onSuccess: async (data) => {
      if (Array.isArray(data.roles)) {
        applyDevRoles(data.roles);
      }
      const refreshed = await refreshPermissions();
      if (!refreshed && Array.isArray(data.roles)) {
        applyDevRoles(data.roles);
      }
      await queryClient.invalidateQueries({ queryKey: ["connectors"] });
      await queryClient.invalidateQueries({
        queryKey: ["connector-user-access"],
      });
      router.refresh();
      toast.success(
        data.role === "admin" ? "Switched to admin" : "Switched to user",
      );
      if (!refreshed) {
        toast.warning("Role updated; permissions refresh failed — retry later");
      }
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  if (!DEV_THEME || !isCloudBrand || (!isAuthenticated && !isNoAuthMode)) {
    return null;
  }

  return (
    <div
      className="flex items-center border border-border rounded-full"
      title="Dev only: switch RBAC role for SaaS UI testing"
    >
      <button
        type="button"
        disabled={mutation.isPending}
        className={`px-3 h-6 rounded-full text-xs font-medium transition-colors disabled:opacity-50 ${
          currentRole === "user"
            ? "bg-foreground text-background"
            : "text-foreground hover:bg-muted"
        }`}
        onClick={() => mutation.mutate("user")}
        data-testid="dev-role-user"
      >
        User
      </button>
      <button
        type="button"
        disabled={mutation.isPending}
        className={`px-3 h-6 rounded-full text-xs font-medium transition-colors disabled:opacity-50 ${
          currentRole === "admin"
            ? "bg-blue-600 text-white"
            : "text-foreground hover:bg-blue-600 hover:text-white"
        }`}
        onClick={() => mutation.mutate("admin")}
        data-testid="dev-role-admin"
      >
        Admin
      </button>
    </div>
  );
}
