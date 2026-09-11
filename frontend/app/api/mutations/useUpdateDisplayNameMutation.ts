import { useMutation } from "@tanstack/react-query";
import { patchDisplayName } from "./useUpdateDisplayNameMutation.helpers";

interface UpdateDisplayNameVariables {
  display_name: string | null;
}

export function useUpdateDisplayNameMutation() {
  return useMutation({
    mutationFn: ({ display_name }: UpdateDisplayNameVariables) =>
      patchDisplayName(display_name),
  });
}
