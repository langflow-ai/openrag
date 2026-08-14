import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  ComponentState,
  ComponentStatus,
  ConsoleStatusResponse,
} from "./useConsoleStatusQuery";

// ─── shared types ──────────────────────────────────────────────────────────

export interface ComponentActionResponse {
  component: string;
  ok: boolean;
  message: string;
  status: ComponentStatus;
}

export interface DiagnosisResponse {
  component: string;
  state: ComponentState;
  summary: string;
  likely_cause?: string | null;
  remediation: string[];
  last_error?: string | null;
  target?: string | null;
}

const SEVERITY: Record<ComponentState, number> = {
  healthy: 0,
  degraded: 1,
  unknown: 2,
  unhealthy: 3,
};

const worstOf = (states: ComponentState[]): ComponentState =>
  states.reduce<ComponentState>(
    (worst, s) => (SEVERITY[s] > SEVERITY[worst] ? s : worst),
    "healthy",
  );

// ─── sync mutation ───────────────────────────────────────────────────────────

/** Re-checks one component and patches the ["console-status"] cache with the
 *  returned fresh status. */
export function useComponentSyncMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (component: string): Promise<ComponentActionResponse> => {
      const res = await fetch(
        `/api/status/${encodeURIComponent(component)}/sync`,
        { method: "POST" },
      );
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof body?.detail === "string" ? body.detail : `HTTP ${res.status}`,
        );
      }
      return body as ComponentActionResponse;
    },
    onSuccess: (result) => {
      queryClient.setQueryData<ConsoleStatusResponse>(
        ["console-status"],
        (prev) => {
          if (!prev) return prev;
          const components = prev.components.map((c) =>
            c.name === result.component ? result.status : c,
          );
          return {
            ...prev,
            components,
            overall_status: worstOf(components.map((c) => c.status)),
          };
        },
      );
    },
  });
}

// ─── diagnose query (lazy — fires when the modal opens) ──────────────────────

export const useComponentDiagnoseQuery = (component: string | null) =>
  useQuery({
    queryKey: ["component-diagnose", component],
    queryFn: async () => {
      const res = await fetch(
        `/api/status/${encodeURIComponent(component as string)}/diagnose`,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json() as Promise<DiagnosisResponse>;
    },
    enabled: !!component,
    staleTime: 5000,
    refetchOnWindowFocus: false,
  });
