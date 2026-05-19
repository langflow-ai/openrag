import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

export interface AdminRole {
  id: string;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions: string[];
}

export const useGetAdminRolesQuery = (
  options?: Omit<UseQueryOptions<AdminRole[]>, "queryKey" | "queryFn">,
) => {
  async function fetchRoles(): Promise<AdminRole[]> {
    const response = await fetch("/api/admin/roles");
    if (response.ok) return await response.json();
    // 403: caller lacks permission. 404: endpoint disabled via
    // OPENRAG_RBAC_UI_ENABLED=false in saas/on_prem. Both render as
    // an empty list so the read-only users surface still works.
    if (response.status === 403 || response.status === 404) return [];
    throw new Error(`Failed to fetch roles (${response.status})`);
  }

  return useQuery({
    queryKey: ["admin-roles"],
    queryFn: fetchRoles,
    ...options,
  });
};
