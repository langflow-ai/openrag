import { type UseQueryOptions, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { isConnectorVisibleInSettings } from "@/lib/settings-tab-access";

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
    ...options,
  });
};

/** Same list as the Connectors tab (hides IBM-only / cloud-excluded types). */
export const useVisibleConnectorAccessQuery = () => {
  const isCloudBrand = useIsCloudBrand();
  const { isIbmAuthMode } = useAuth();
  const query = useGetConnectorAccessQuery();
  const connectors = useMemo(
    () =>
      (query.data ?? []).filter((c) =>
        isConnectorVisibleInSettings(c.type, { isCloudBrand, isIbmAuthMode }),
      ),
    [query.data, isCloudBrand, isIbmAuthMode],
  );
  return { ...query, connectors };
};
