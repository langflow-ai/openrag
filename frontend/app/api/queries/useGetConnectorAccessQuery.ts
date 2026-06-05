import { type UseQueryOptions, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";

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

/** Same deployment filter as the Connectors tab (IBM-only / cloud-excluded types). */
export const useVisibleConnectorAccessQuery = () => {
  const isCloudBrand = useIsCloudBrand();
  const { isIbmAuthMode } = useAuth();
  const query = useGetConnectorAccessQuery();
  const connectors = useMemo(
    () =>
      (query.data ?? []).filter((c) => {
        if (c.type === "ibm_cos" || c.type === "aws_s3") return isIbmAuthMode;
        if (isCloudBrand && c.type === "onedrive") return false;
        return true;
      }),
    [query.data, isCloudBrand, isIbmAuthMode],
  );
  return { ...query, connectors };
};
