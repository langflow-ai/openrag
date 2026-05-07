import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

export interface AdminUser {
  id: string;
  oauth_provider: string;
  oauth_subject: string;
  email: string | null;
  display_name: string | null;
  picture_url: string | null;
  is_active: boolean;
  roles: string[];
  created_at: string | null;
  last_login: string | null;
}

export const useGetAdminUsersQuery = (
  options?: Omit<UseQueryOptions<AdminUser[]>, "queryKey" | "queryFn">,
) => {
  async function fetchUsers(): Promise<AdminUser[]> {
    const response = await fetch("/api/admin/users");
    if (response.ok) return await response.json();
    if (response.status === 403) return [];
    throw new Error(`Failed to fetch users (${response.status})`);
  }

  return useQuery({
    queryKey: ["admin-users"],
    queryFn: fetchUsers,
    ...options,
  });
};
