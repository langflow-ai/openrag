import { useMutation, useQueryClient } from "@tanstack/react-query";

interface RevokeRoleVariables {
  user_id: string;
  role_id: string;
}

export const useRevokeRoleMutation = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ user_id, role_id }: RevokeRoleVariables) => {
      const response = await fetch(
        `/api/admin/users/${user_id}/roles/${role_id}`,
        { method: "DELETE" },
      );
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err?.detail?.error || "Failed to revoke role");
      }
      return await response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });
};
