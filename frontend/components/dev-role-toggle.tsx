"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { IBM_THEME_DEV } from "@/lib/brand";

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

// Built-in roles, highest-privilege first. Drives the dev-only role switcher;
// order also sets which role is highlighted when a user holds several.
const DEV_ROLES = [
  { value: "admin", label: "Admin" },
  { value: "developer", label: "Developer" },
  { value: "user", label: "User" },
  { value: "viewer", label: "Viewer" },
] as const;

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
  const currentRole =
    DEV_ROLES.find((r) => roles.includes(r.value))?.value ?? "user";

  const mutation = useMutation({
    mutationFn: async (role: string) => {
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
      const label =
        DEV_ROLES.find((r) => r.value === data.role)?.label ?? data.role;
      toast.success(`Switched to ${label}`);
      if (!refreshed) {
        toast.warning("Role updated; permissions refresh failed — retry later");
      }
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  if (!IBM_THEME_DEV || !isCloudBrand || (!isAuthenticated && !isNoAuthMode)) {
    return null;
  }

  return (
    <div
      className="flex items-center border border-border rounded-full"
      title="Dev only: switch RBAC role for SaaS UI testing"
    >
      {DEV_ROLES.map((role) => (
        <button
          key={role.value}
          type="button"
          disabled={mutation.isPending}
          className={`px-3 h-6 rounded-full text-xs font-medium transition-colors disabled:opacity-50 ${
            currentRole === role.value
              ? "bg-blue-600 text-white"
              : "text-foreground hover:bg-blue-600 hover:text-white"
          }`}
          onClick={() => mutation.mutate(role.value)}
          data-testid={`dev-role-${role.value}`}
        >
          {role.label}
        </button>
      ))}
    </div>
  );
}
