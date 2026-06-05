import { type UseQueryOptions, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useConnectorSettingsVisibility } from "@/hooks/use-settings-tab-access";
import { filterConnectorsVisibleInSettings } from "@/lib/settings-tab-access";

export interface ConnectorAccessItem {
  type: string;
  name: string;
  enabled: boolean;
}

export const useGetConnectorAccessQuery = (
  options?: Omit<
    UseQueryOptions<ConnectorAccessItem[]>,
    "queryKey" | "queryFn"
  >,
) => {
  async function fetchConnectorAccess(): Promise<ConnectorAccessItem[]> {
    const response = await fetch("/api/connectors/user-access");
    if (!response.ok) {
      throw new Error(
        `Failed to fetch connectors permission (${response.status})`,
      );
    }
    const data = await response.json();
    return Array.isArray(data.connectors) ? data.connectors : [];
  }

  return useQuery({
    queryKey: ["connector-user-access"],
    queryFn: fetchConnectorAccess,
    refetchOnWindowFocus: false,
    ...options,
  });
};

/** Same list as the Connectors tab (hides IBM-only / cloud-excluded types). */
export const useVisibleConnectorAccessQuery = () => {
  const visibility = useConnectorSettingsVisibility();
  const query = useGetConnectorAccessQuery();
  const connectors = useMemo(
    () => filterConnectorsVisibleInSettings(query.data ?? [], visibility),
    [query.data, visibility],
  );
  return { ...query, connectors };
};
