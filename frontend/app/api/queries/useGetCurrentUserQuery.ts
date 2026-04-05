import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export interface CurrentUser {
  user_id: string;
  email: string;
  name: string;
}

async function fetchCurrentUser(): Promise<CurrentUser> {
  const response = await fetch("/api/auth/me");
  if (!response.ok) {
    throw new Error("Failed to fetch current user");
  }
  return response.json();
}

export const useGetCurrentUserQuery = (
  options?: Omit<UseQueryOptions<CurrentUser>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  return useQuery(
    {
      queryKey: ["current-user"],
      queryFn: fetchCurrentUser,
      staleTime: 1000 * 60 * 30, // 30 minutes — user identity doesn't change mid-session
      ...options,
    },
    queryClient,
  );
};
