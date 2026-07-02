"use client";

import type { useSyncConnector } from "@/app/api/mutations/useSyncConnector";
import type { Connector } from "@/app/api/queries/useGetConnectorsQuery";
import { SharedBucketView } from "@/components/connectors/shared-bucket-view";
import { useAzureBlobContainerStatusQuery } from "../useAzureBlobContainerStatusQuery";

export interface AzureBlobBucketViewProps {
  connector: Connector;
  syncMutation: ReturnType<typeof useSyncConnector>;
  addTask: (id: string, options?: { connectorType?: string }) => void;
  onBack: () => void;
  onDone: () => void;
}

export function AzureBlobBucketView({
  connector,
  syncMutation,
  addTask,
  onBack,
  onDone,
}: AzureBlobBucketViewProps) {
  const {
    data: containers,
    isLoading,
    error: containersError,
    refetch,
  } = useAzureBlobContainerStatusQuery(connector.connectionId, {
    enabled: true,
  });
  return (
    <SharedBucketView
      connector={connector}
      buckets={containers}
      isLoading={isLoading}
      bucketsError={containersError as Error | null}
      onRefetch={refetch}
      invalidateQueryKey={[
        "azure-blob-container-status",
        connector.connectionId,
      ]}
      syncMutation={syncMutation}
      addTask={addTask}
      onBack={onBack}
      onDone={onDone}
    />
  );
}
