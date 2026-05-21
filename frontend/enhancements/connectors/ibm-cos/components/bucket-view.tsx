"use client";

import type { useSyncConnector } from "@/app/api/mutations/useSyncConnector";
import { SharedBucketView } from "@/components/connectors/shared-bucket-view";
import { useIBMCOSBucketStatusQuery } from "../useIBMCOSBucketStatusQuery";

export interface IBMCOSBucketViewProps {
  connector: any;
  syncMutation: ReturnType<typeof useSyncConnector>;
  addTask: (id: string) => void;
  onBack: () => void;
  onDone: () => void;
}

export function IBMCOSBucketView({
  connector,
  syncMutation,
  addTask,
  onBack,
  onDone,
}: IBMCOSBucketViewProps) {
  const {
    data: buckets,
    isLoading,
    error: bucketsError,
    refetch,
  } = useIBMCOSBucketStatusQuery(connector.connectionId, { enabled: true });
  return (
    <SharedBucketView
      connector={connector}
      buckets={buckets}
      isLoading={isLoading}
      bucketsError={bucketsError as Error | null}
      onRefetch={refetch}
      invalidateQueryKey={["ibm-cos-bucket-status", connector.connectionId]}
      syncMutation={syncMutation}
      addTask={addTask}
      onBack={onBack}
      onDone={onDone}
    />
  );
}
