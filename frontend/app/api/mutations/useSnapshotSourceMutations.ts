import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  type SnapshotSource,
  type SnapshotSourceInput,
  snapshotKeys,
  snapshotRequest,
} from "@/lib/opensearch-snapshot";

export function useCreateSnapshotSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: SnapshotSourceInput) =>
      snapshotRequest<SnapshotSource>("/sources", {
        method: "POST",
        body: input,
        fallbackError: "Could not create the snapshot source",
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: snapshotKeys.sources }),
  });
}

export function useUpdateSnapshotSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      input,
    }: {
      id: string;
      input: Partial<SnapshotSourceInput>;
    }) =>
      snapshotRequest<SnapshotSource>(`/sources/${id}`, {
        method: "PATCH",
        body: input,
        fallbackError: "Could not update the snapshot source",
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: snapshotKeys.sources }),
  });
}

export function useDeleteSnapshotSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      snapshotRequest<unknown>(`/sources/${id}`, {
        method: "DELETE",
        fallbackError: "Could not delete the snapshot source",
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: snapshotKeys.sources }),
  });
}
