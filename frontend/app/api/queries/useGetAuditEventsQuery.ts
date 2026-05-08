import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

export interface AuditEvent {
  id: string;
  ts: string;
  actor_user_id: string | null;
  event: string;
  target_type: string | null;
  target_id: string | null;
  audit_metadata: Record<string, unknown> | null;
}

interface AuditQueryParams {
  limit?: number;
  offset?: number;
}

export const useGetAuditEventsQuery = (
  params: AuditQueryParams = {},
  options?: Omit<UseQueryOptions<AuditEvent[]>, "queryKey" | "queryFn">,
) => {
  const { limit = 20, offset = 0 } = params;

  async function fetchAudit(): Promise<AuditEvent[]> {
    const qs = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    const response = await fetch(`/api/admin/audit?${qs.toString()}`);
    if (response.ok) return await response.json();
    if (response.status === 403) return [];
    throw new Error(`Failed to fetch audit log (${response.status})`);
  }

  return useQuery({
    queryKey: ["admin-audit", limit, offset],
    queryFn: fetchAudit,
    ...options,
  });
};
