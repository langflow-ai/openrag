import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  type AnalyserFileUpload,
  type PreflightResult,
  type SnapshotDataset,
  type SnapshotImport,
  type SnapshotImportAccepted,
  type StartImportRequest,
  snapshotKeys,
  snapshotRequest,
} from "@/lib/opensearch-snapshot";

function useInvalidateImports() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      // Prefix of every `import(id)` key as well.
      queryClient.invalidateQueries({ queryKey: snapshotKeys.imports }),
      queryClient.invalidateQueries({ queryKey: snapshotKeys.datasets }),
    ]);
}

export function usePreflightSnapshot() {
  return useMutation({
    mutationFn: ({
      sourceId,
      snapshot,
      indices,
    }: {
      sourceId: string;
      snapshot: string;
      indices: string[];
    }) =>
      snapshotRequest<PreflightResult>(`/sources/${sourceId}/preflight`, {
        method: "POST",
        body: { snapshot, indices },
        fallbackError: "Preflight checks could not be run",
      }),
  });
}

export function useStartSnapshotImport() {
  const invalidate = useInvalidateImports();
  return useMutation({
    mutationFn: (request: StartImportRequest) =>
      snapshotRequest<SnapshotImportAccepted>("/imports", {
        method: "POST",
        body: request,
        fallbackError: "Could not start the import",
      }),
    onSuccess: invalidate,
  });
}

export interface DatasetPatch {
  display_name?: string;
  description?: string;
  field_map?: SnapshotDataset["field_map"];
  retrieval?: SnapshotDataset["retrieval"];
}

export function usePatchSnapshotDataset() {
  const invalidate = useInvalidateImports();
  return useMutation({
    mutationFn: ({
      importId,
      datasetId,
      patch,
    }: {
      importId: string;
      datasetId: string;
      patch: DatasetPatch;
    }) =>
      snapshotRequest<SnapshotDataset>(
        `/imports/${importId}/datasets/${datasetId}`,
        {
          method: "PATCH",
          body: patch,
          fallbackError: "Could not save the dataset",
        },
      ),
    onSuccess: invalidate,
  });
}

export function useActivateSnapshotImport() {
  const invalidate = useInvalidateImports();
  return useMutation({
    mutationFn: (importId: string) =>
      snapshotRequest<SnapshotImport>(`/imports/${importId}/activate`, {
        method: "POST",
        fallbackError: "Could not activate the import",
      }),
    onSuccess: invalidate,
  });
}

export function useShareSnapshotImport() {
  const invalidate = useInvalidateImports();
  return useMutation({
    mutationFn: ({ importId, shared }: { importId: string; shared: boolean }) =>
      snapshotRequest<SnapshotImport>(`/imports/${importId}/share`, {
        method: "POST",
        body: { shared },
        fallbackError: "Could not change sharing",
      }),
    onSuccess: invalidate,
  });
}

export function useReimportPreflight() {
  return useMutation({
    mutationFn: ({
      importId,
      snapshot,
    }: {
      importId: string;
      snapshot: string;
    }) =>
      snapshotRequest<PreflightResult>(
        `/imports/${importId}/reimport/preflight`,
        {
          method: "POST",
          body: { snapshot },
          fallbackError: "Re-import checks could not be run",
        },
      ),
  });
}

export function useReimportSnapshot() {
  const invalidate = useInvalidateImports();
  return useMutation({
    mutationFn: ({
      importId,
      snapshot,
      analyserFiles,
    }: {
      importId: string;
      snapshot: string;
      analyserFiles: AnalyserFileUpload[];
    }) =>
      snapshotRequest<SnapshotImportAccepted>(`/imports/${importId}/reimport`, {
        method: "POST",
        body: { snapshot, analyser_files: analyserFiles },
        fallbackError: "Could not start the re-import",
      }),
    onSuccess: invalidate,
  });
}

export function useDeleteSnapshotImport() {
  const invalidate = useInvalidateImports();
  return useMutation({
    mutationFn: (importId: string) =>
      snapshotRequest<{ import: SnapshotImport }>(`/imports/${importId}`, {
        method: "DELETE",
        fallbackError: "Could not delete the import",
      }),
    onSuccess: invalidate,
  });
}
