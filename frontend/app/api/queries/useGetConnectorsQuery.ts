import {
  type QueryClient,
  type UseQueryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "@/contexts/auth-context";
import { useBrand, useIsCloudBrand } from "@/contexts/brand-context";
import {
  isConnectorShownInWorkspace,
  isConnectorTypeVisible,
  isSaasPolicyContext,
} from "@/lib/brand";

/** Prefix for all connector list queries (see `connectorsQueryKey`). */
export const CONNECTORS_QUERY_KEY_ROOT = ["connectors"] as const;

/**
 * Cache key from policy + deployment filter context (inputs to `getConnectors`).
 * `cloudContext`: backend `/api/connectors` filtering (server policy).
 * `applyWorkspacePolicy`: SaaS workspace policy path in the query fn.
 * `isCloudBrand` / `isIbmAuthMode`: client deployment visibility (`isConnectorTypeVisible`).
 */
export function connectorsQueryKey(
  cloudContext: boolean,
  applyWorkspacePolicy: boolean,
  isCloudBrand: boolean,
  isIbmAuthMode: boolean,
) {
  return [
    ...CONNECTORS_QUERY_KEY_ROOT,
    cloudContext,
    applyWorkspacePolicy,
    isCloudBrand,
    isIbmAuthMode,
  ] as const;
}

export type ConnectorsQueryKey = ReturnType<typeof connectorsQueryKey>;

/** Snapshot of every cached connector list — safe across policy key changes. */
export type ConnectorsMutationContext = {
  previousByKey: Array<[ConnectorsQueryKey, Connector[] | undefined]>;
};

export function snapshotConnectorQueries(
  queryClient: QueryClient,
): ConnectorsMutationContext {
  return {
    previousByKey: queryClient
      .getQueriesData<Connector[]>(connectorsQueryFilter)
      .map(([queryKey, data]) => [queryKey as ConnectorsQueryKey, data]),
  };
}

export function restoreConnectorQueries(
  queryClient: QueryClient,
  context?: ConnectorsMutationContext,
): void {
  context?.previousByKey.forEach(([queryKey, data]) => {
    if (data !== undefined) {
      queryClient.setQueryData(queryKey, data);
    }
  });
}

export function updateAllConnectorQueries(
  queryClient: QueryClient,
  updater: (connectors: Connector[]) => Connector[],
): void {
  queryClient
    .getQueriesData<Connector[]>(connectorsQueryFilter)
    .forEach(([queryKey, data]) => {
      if (data !== undefined) {
        queryClient.setQueryData(queryKey as ConnectorsQueryKey, updater(data));
      }
    });
}

/** Shared policy context for connector list query key + optimistic updates. */
export function useConnectorsQueryKey() {
  const { isIbmAuthMode, cloudContext } = useAuth();
  const { brand } = useBrand();
  const isCloudBrand = useIsCloudBrand();
  const applyWorkspacePolicy = isSaasPolicyContext({
    isIbmAuthMode,
    cloudContext,
    brand,
  });
  return {
    cloudContext,
    applyWorkspacePolicy,
    isCloudBrand,
    isIbmAuthMode,
    queryKey: connectorsQueryKey(
      cloudContext,
      applyWorkspacePolicy,
      isCloudBrand,
      isIbmAuthMode,
    ),
  };
}

/** Match every `["connectors", …]` query — required for invalidate/cancel after key shape change. */
export const connectorsQueryFilter = {
  queryKey: CONNECTORS_QUERY_KEY_ROOT,
  exact: false,
} as const;

interface GoogleDriveFile {
  id: string;
  name: string;
  mimeType: string;
  webViewLink?: string;
  iconLink?: string;
}

interface OneDriveFile {
  id: string;
  name: string;
  mimeType?: string;
  webUrl?: string;
  driveItem?: {
    file?: { mimeType: string };
    folder?: unknown;
  };
}

export interface Connector {
  id: string;
  name: string;
  description: string;
  icon: string; // The icon name from the API
  status: "not_connected" | "connected" | "error";
  type: string;
  connectionId?: string;
  clientId?: string;
  baseUrl?: string;
  access_token?: string;
  selectedFiles?: GoogleDriveFile[] | OneDriveFile[];
  available?: boolean;
}

interface Connection {
  connection_id: string;
  is_active: boolean;
  is_authenticated?: boolean;
  created_at: string;
  last_sync?: string;
  client_id?: string;
  base_url?: string;
}

export interface GetConnectorsResponse {
  connectors: Connector[];
}

async function fetchWorkspaceConnectorAccess(): Promise<
  Record<string, boolean>
> {
  const response = await fetch("/api/connectors/workspace-policy");
  if (!response.ok) return {};
  const data = await response.json();
  return data?.access && typeof data.access === "object" ? data.access : {};
}

export const useGetConnectorsQuery = (
  options?: Omit<UseQueryOptions<Connector[]>, "queryKey" | "queryFn">,
) => {
  const { applyWorkspacePolicy, isCloudBrand, isIbmAuthMode, queryKey } =
    useConnectorsQueryKey();

  async function getConnectors(): Promise<Connector[]> {
    const connectorsResponse = await fetch("/api/connectors");
    if (!connectorsResponse.ok) {
      throw new Error("Failed to fetch available connectors");
    }

    const { connectors: connectorsMap } = await connectorsResponse.json();
    const connectorTypes = Object.keys(connectorsMap);

    const connectorsWithStatus = await Promise.all(
      connectorTypes.map(async (type) => {
        const connectorData = connectorsMap[type];
        const statusResponse = await fetch(`/api/connectors/${type}/status`);

        let status: Connector["status"] = "not_connected";
        let connectionId: string | undefined;

        if (statusResponse.ok) {
          const statusData = await statusResponse.json();
          const connections = statusData.connections || [];
          const activeConnection = connections.find(
            (conn: Connection) => conn.is_active && conn.is_authenticated,
          );

          if (activeConnection) {
            status = "connected";
            connectionId = activeConnection.connection_id;
            return {
              id: type,
              name: connectorData.name,
              description: connectorData.description,
              icon: connectorData.icon,
              status,
              type,
              connectionId,
              clientId: activeConnection.client_id,
              baseUrl: activeConnection.base_url,
              available: connectorData.available,
            } as Connector;
          }
        }

        return {
          id: type,
          name: connectorData.name,
          description: connectorData.description,
          icon: connectorData.icon,
          status,
          type,
          connectionId,
          available: connectorData.available,
        } as Connector;
      }),
    );

    let result = connectorsWithStatus;
    const deploymentCtx = { isCloudBrand, isIbmAuthMode };

    if (applyWorkspacePolicy) {
      const storedAccess = await fetchWorkspaceConnectorAccess();
      result = result.filter((c) =>
        isConnectorShownInWorkspace(c.type, storedAccess, deploymentCtx),
      );
    } else {
      result = result.filter((c) =>
        isConnectorTypeVisible(c.type, deploymentCtx),
      );
    }

    return result;
  }

  return useQuery({
    queryKey,
    queryFn: getConnectors,
    refetchOnMount: "always",
    ...options,
  });
};

export interface ConnectorAccessItem {
  type: string;
  name: string;
  enabled: boolean;
}

export const CONNECTOR_USER_ACCESS_KEY = ["connector-user-access"] as const;

export function connectorUserAccessQueryKey(
  isCloudBrand: boolean,
  isIbmAuthMode: boolean,
) {
  return [...CONNECTOR_USER_ACCESS_KEY, isCloudBrand, isIbmAuthMode] as const;
}

function filterConnectorAccessItems(
  connectors: ConnectorAccessItem[],
  deploymentCtx: { isCloudBrand: boolean; isIbmAuthMode: boolean },
): ConnectorAccessItem[] {
  return connectors.filter((c) =>
    isConnectorTypeVisible(c.type, deploymentCtx),
  );
}

export const useGetConnectorAccessQuery = (
  options?: Omit<
    UseQueryOptions<ConnectorAccessItem[]>,
    "queryKey" | "queryFn"
  >,
) => {
  const isCloudBrand = useIsCloudBrand();
  const { isIbmAuthMode } = useAuth();

  async function fetchConnectorAccess(): Promise<ConnectorAccessItem[]> {
    const response = await fetch("/api/connectors/user-access");
    if (!response.ok) {
      throw new Error(
        `Failed to fetch connectors permission (${response.status})`,
      );
    }
    const data = await response.json();
    const connectors = Array.isArray(data.connectors) ? data.connectors : [];
    const deploymentCtx = { isCloudBrand, isIbmAuthMode };
    return filterConnectorAccessItems(connectors, deploymentCtx);
  }

  return useQuery({
    queryKey: connectorUserAccessQueryKey(isCloudBrand, isIbmAuthMode),
    queryFn: fetchConnectorAccess,
    refetchOnWindowFocus: false,
    ...options,
  });
};

export const useUpdateConnectorAccessMutation = () => {
  const queryClient = useQueryClient();
  const isCloudBrand = useIsCloudBrand();
  const { isIbmAuthMode } = useAuth();
  const deploymentCtx = { isCloudBrand, isIbmAuthMode };
  const accessQueryKey = connectorUserAccessQueryKey(
    isCloudBrand,
    isIbmAuthMode,
  );

  return useMutation({
    mutationFn: async (
      access: Record<string, boolean>,
    ): Promise<ConnectorAccessItem[]> => {
      const response = await fetch("/api/connectors/user-access", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ access }),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(
          result.error || "Failed to update connectors permission",
        );
      }
      const data = await response.json();
      const connectors = Array.isArray(data.connectors) ? data.connectors : [];
      return filterConnectorAccessItems(connectors, deploymentCtx);
    },
    onSuccess: (connectors) => {
      queryClient.setQueryData(accessQueryKey, connectors);
      queryClient.invalidateQueries(connectorsQueryFilter);
      toast.success("Connectors permission saved");
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
};
