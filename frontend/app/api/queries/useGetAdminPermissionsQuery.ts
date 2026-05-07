import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

export interface AdminPermission {
  id: string;
  name: string;
  resource: string;
  action: string;
  description: string | null;
}

export const useGetAdminPermissionsQuery = (
  options?: Omit<UseQueryOptions<AdminPermission[]>, "queryKey" | "queryFn">,
) => {
  async function fetchPermissions(): Promise<AdminPermission[]> {
    const response = await fetch("/api/admin/permissions");
    if (response.ok) return await response.json();
    if (response.status === 403) return [];
    throw new Error(`Failed to fetch permissions (${response.status})`);
  }

  return useQuery({
    queryKey: ["admin-permissions"],
    queryFn: fetchPermissions,
    ...options,
  });
};
