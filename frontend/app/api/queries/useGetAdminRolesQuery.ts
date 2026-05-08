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
    if (response.status === 403) return [];
    throw new Error(`Failed to fetch roles (${response.status})`);
  }

  return useQuery({
    queryKey: ["admin-roles"],
    queryFn: fetchRoles,
    ...options,
  });
};
