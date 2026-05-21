"use client";

import type { useSyncConnector } from "@/app/api/mutations/useSyncConnector";
import { useS3BucketStatusQuery } from "@/app/api/queries/useS3BucketStatusQuery";
import { SharedBucketView } from "../shared-bucket-view";

export interface S3BucketViewProps {
  connector: any;
  syncMutation: ReturnType<typeof useSyncConnector>;
  addTask: (id: string) => void;
  onBack: () => void;
  onDone: () => void;
}

export function S3BucketView({
  connector,
  syncMutation,
  addTask,
  onBack,
  onDone,
}: S3BucketViewProps) {
  const {
    data: buckets,
    isLoading,
    error: bucketsError,
    refetch,
  } = useS3BucketStatusQuery(connector.connectionId, { enabled: true });
  return (
    <SharedBucketView
      connector={connector}
      buckets={buckets}
      isLoading={isLoading}
      bucketsError={bucketsError as Error | null}
      onRefetch={refetch}
      invalidateQueryKey={["s3-bucket-status", connector.connectionId]}
      syncMutation={syncMutation}
      addTask={addTask}
      onBack={onBack}
      onDone={onDone}
    />
  );
}
