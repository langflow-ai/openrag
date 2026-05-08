import { useMutation, useQueryClient } from "@tanstack/react-query";

interface AssignRoleVariables {
  user_id: string;
  role_id: string;
}

export const useAssignRoleMutation = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ user_id, role_id }: AssignRoleVariables) => {
      const response = await fetch(`/api/admin/users/${user_id}/roles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role_id }),
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err?.detail?.error || "Failed to assign role");
      }
      return await response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });
};
