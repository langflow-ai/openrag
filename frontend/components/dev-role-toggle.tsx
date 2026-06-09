"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  CONNECTOR_USER_ACCESS_KEY,
  connectorsQueryFilter,
} from "@/app/api/queries/useGetConnectorsQuery";
import { useAuth } from "@/contexts/auth-context";
import { useBrand } from "@/contexts/brand-context";
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

const DEV_ROLES = [
  { value: "admin", label: "Admin" },
  { value: "developer", label: "Developer" },
  { value: "user", label: "User" },
  { value: "viewer", label: "Viewer" },
] as const;

export function DevRoleToggle() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { roles, isAuthenticated, isNoAuthMode, refreshPermissions } =
    useAuth();
  const { brand } = useBrand();
  const currentRole = DEV_ROLES.find((r) => roles.includes(r.value))?.value;

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
      return response.json() as Promise<{ role?: string }>;
    },
    onSuccess: async (data) => {
      await refreshPermissions();
      await queryClient.invalidateQueries(connectorsQueryFilter);
      await queryClient.invalidateQueries({
        queryKey: CONNECTOR_USER_ACCESS_KEY,
      });
      router.refresh();
      const label =
        DEV_ROLES.find((r) => r.value === data.role)?.label ?? data.role;
      toast.success(`Switched to ${label}`);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  if (
    !IBM_THEME_DEV ||
    brand === "oss" ||
    (!isAuthenticated && !isNoAuthMode)
  ) {
    return null;
  }

  return (
    <div
      className="flex items-center gap-0.5 border border-border rounded-full px-0.5"
      title="Dev only: switch RBAC role for UI testing"
    >
      {DEV_ROLES.map((role) => (
        <button
          key={role.value}
          type="button"
          disabled={mutation.isPending}
          className={`px-2 h-6 rounded-full text-[11px] font-medium transition-colors disabled:opacity-50 ${
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
