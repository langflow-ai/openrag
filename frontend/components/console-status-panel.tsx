"use client";

import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  EvCharger,
  HelpCircle,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { useCallback, useState } from "react";
import {
  type ComponentState,
  type ComponentStatus,
  useConsoleStatusQuery,
} from "@/app/api/queries/useConsoleStatusQuery";
import type { ProviderHealthResponse } from "@/app/api/queries/useProviderHealthQuery";
import { useProviderHealth } from "@/components/provider-health-banner";
import { cn } from "@/lib/utils";

// ─── status helpers ──────────────────────────────────────────────────────────

function statusColor(status: ComponentState) {
  switch (status) {
    case "healthy":
      return "text-emerald-400";
    case "degraded":
      return "text-amber-400";
    case "unhealthy":
      return "text-red-400";
    default:
      return "text-zinc-400";
  }
}

function statusBadgeCls(status: ComponentState) {
  switch (status) {
    case "healthy":
      return "bg-emerald-500/15 text-emerald-400 border-emerald-500/30";
    case "degraded":
      return "bg-amber-500/15 text-amber-400 border-amber-500/30";
    case "unhealthy":
      return "bg-red-500/15 text-red-400 border-red-500/30";
    default:
      return "bg-zinc-500/15 text-zinc-400 border-zinc-500/30";
  }
}

function StatusIcon({
  status,
  size = 16,
}: {
  status: ComponentState;
  size?: number;
}) {
  switch (status) {
    case "healthy":
      return <CheckCircle2 size={size} className="text-emerald-400 shrink-0" />;
    case "degraded":
      return <AlertTriangle size={size} className="text-amber-400 shrink-0" />;
    case "unhealthy":
      return <XCircle size={size} className="text-red-400 shrink-0" />;
    default:
      return <HelpCircle size={size} className="text-zinc-400 shrink-0" />;
  }
}

// ─── summary placard ─────────────────────────────────────────────────────────

interface SummaryCardProps {
  label: string;
  count: number;
  state: ComponentState;
}

function SummaryCard({ label, count, state }: SummaryCardProps) {
  const colorClass = statusColor(state);
  return (
    <div className="flex-1 rounded-lg bg-zinc-800/60 border border-zinc-700/50 px-3 py-2.5">
      <p className="text-[11px] font-medium text-zinc-400 uppercase tracking-wide">
        {label}
      </p>
      <p className={cn("text-2xl font-semibold mt-0.5", colorClass)}>{count}</p>
    </div>
  );
}

// ─── metadata row ────────────────────────────────────────────────────────────

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2 py-1">
      <span className="text-xs text-zinc-500 shrink-0">{label}</span>
      <span className="text-xs text-zinc-300 text-right truncate max-w-[60%]">
        {value}
      </span>
    </div>
  );
}

// ─── component placard ───────────────────────────────────────────────────────

interface ComponentCardProps {
  component: ComponentStatus;
}

function ComponentCard({ component }: ComponentCardProps) {
  const [expanded, setExpanded] = useState(false);

  const {
    display_name,
    status,
    version,
    latency_ms,
    message,
    build,
    metadata,
  } = component;

  const hasBuildDetails =
    build &&
    (build.git_sha || build.build_time || build.image || build.image_digest);
  const hasMetadata = metadata && Object.keys(metadata).length > 0;

  return (
    <div
      className={cn(
        "rounded-xl border bg-zinc-800/60 transition-colors",
        expanded ? "border-zinc-600/70" : "border-zinc-700/50",
      )}
    >
      {/* Header row — always clickable; chevron always visible */}
      <button
        type="button"
        className="w-full flex items-center gap-3 px-3.5 py-3 text-left"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <StatusIcon status={status} size={16} />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-zinc-100">
              {display_name}
            </span>
            <span
              className={cn(
                "inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold border capitalize",
                statusBadgeCls(status),
              )}
            >
              {status}
            </span>
            {version && (
              <span className="text-[11px] text-zinc-500">• v{version}</span>
            )}
          </div>
          {message && (
            <p className="text-xs text-zinc-400 mt-0.5 truncate">{message}</p>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {latency_ms != null && (
            <span className="text-[11px] text-zinc-500 tabular-nums">
              {latency_ms}ms
            </span>
          )}
          <span className="text-zinc-500">
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </span>
        </div>
      </button>

      {/* Expanded details */}
      {expanded && (
        <div className="border-t border-zinc-700/50 px-3.5 py-2.5 space-y-1">
          {hasBuildDetails ? (
            <>
              {build?.git_sha && (
                <MetaRow label="Git SHA" value={build.git_sha.slice(0, 12)} />
              )}
              {build?.build_time && (
                <MetaRow label="Build Time" value={build.build_time} />
              )}
              {build?.image && <MetaRow label="Image" value={build.image} />}
              {build?.image_digest && (
                <MetaRow
                  label="Digest"
                  value={`${build.image_digest.slice(0, 20)}…`}
                />
              )}
            </>
          ) : null}
          {hasMetadata
            ? Object.entries(metadata).map(([k, v]) => (
                <MetaRow key={k} label={k} value={String(v)} />
              ))
            : null}
          {!hasBuildDetails && !hasMetadata && (
            <p className="text-xs text-zinc-500 italic">
              No additional details available.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── provider / api-key health ───────────────────────────────────────────────

/** Map the /provider/health status onto the console-status component states. */
function providerHealthState(
  status: ProviderHealthResponse["status"],
): ComponentState {
  switch (status) {
    case "healthy":
      return "healthy";
    case "unhealthy":
    case "error":
      return "unhealthy";
    default:
      // "backend-unavailable" (or anything unexpected) — can't determine.
      return "unknown";
  }
}

/** Prefer the specific llm/embedding key errors; fall back to the summary. */
function providerHealthMessage(health: ProviderHealthResponse): string {
  if (health.status === "healthy") {
    return health.message || "Providers configured and validated";
  }
  const { llm_error: llmError, embedding_error: embeddingError } = health;
  if (llmError && embeddingError) {
    return llmError === embeddingError
      ? llmError
      : `${llmError}; ${embeddingError}`;
  }
  return (
    llmError || embeddingError || health.message || "Provider validation failed"
  );
}

/** Adapt a provider-health response into a synthetic status component so the
 *  panel renders API-key health with the same card UI as backend components. */
function providerHealthToComponent(
  health: ProviderHealthResponse,
): ComponentStatus {
  const metadata: Record<string, unknown> = {};
  const llmProvider = health.llm_provider ?? health.provider;
  if (llmProvider) metadata["LLM provider"] = llmProvider;
  if (health.embedding_provider) {
    metadata["Embedding provider"] = health.embedding_provider;
  }
  if (health.details?.llm_model) {
    metadata["LLM model"] = health.details.llm_model;
  }
  if (health.details?.embedding_model) {
    metadata["Embedding model"] = health.details.embedding_model;
  }

  return {
    name: "providers",
    display_name: "Model Providers",
    status: providerHealthState(health.status),
    required: true,
    message: providerHealthMessage(health),
    metadata,
  };
}

// ─── main panel ──────────────────────────────────────────────────────────────

interface ConsoleStatusPanelProps {
  onClose: () => void;
}

export function ConsoleStatusPanel({ onClose }: ConsoleStatusPanelProps) {
  const {
    data,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
    dataUpdatedAt,
  } = useConsoleStatusQuery();

  const handleRefresh = useCallback(() => {
    void refetch();
  }, [refetch]);

  // Reuses the shared /provider/health query (same cache as the banner), so an
  // API-key failure surfaces here without an extra network round-trip.
  const { health: providerHealth } = useProviderHealth();

  // Defensive: always read from data.components array
  const backendComponents = Array.isArray(data?.components)
    ? data.components
    : [];

  // Append provider / API-key health as a card so the panel is the single
  // place to spot a key failure. Skipped while the query has no result yet
  // (e.g. non-admins under RBAC, or during active ingestion).
  const components = providerHealth
    ? [...backendComponents, providerHealthToComponent(providerHealth)]
    : backendComponents;

  const counts = {
    healthy: components.filter((c) => c.status === "healthy").length,
    degraded: components.filter((c) => c.status === "degraded").length,
    unhealthy: components.filter((c) => c.status === "unhealthy").length,
    unknown: components.filter((c) => c.status === "unknown").length,
  };

  const lastUpdated = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString()
    : null;

  return (
    /*
     * Floating card — portalled into document.body so this fixed position
     * is always relative to the true viewport (no transformed ancestors).
     * bottom-[5.5rem] clears the button (40px tall) + 24px gap.
     */
    <div
      className={cn(
        "fixed right-6 top-[64px] z-[9999]",
        "w-[440px] max-h-[calc(100vh-8rem)] flex flex-col",
        "bg-zinc-900 border border-zinc-700/70 rounded-2xl shadow-2xl overflow-hidden",
      )}
    >
      {/* Panel header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700/60 shrink-0">
        <div className="flex items-center gap-2">
          <EvCharger size={15} className="text-zinc-400" />
          <h2 className="text-sm font-semibold text-zinc-100">
            Console Status
          </h2>
          {isFetching && (
            <RefreshCw size={12} className="text-zinc-500 animate-spin" />
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-zinc-500 hover:text-zinc-300 transition-colors p-1 rounded hover:bg-zinc-700/50"
          aria-label="Close console status"
        >
          <XCircle size={16} />
        </button>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto scrollbar-hide px-4 py-3 space-y-3">
        {/* Summary placards row */}
        <div className="grid grid-cols-4 gap-2">
          <SummaryCard label="Healthy" count={counts.healthy} state="healthy" />
          <SummaryCard
            label="Degraded"
            count={counts.degraded}
            state="degraded"
          />
          <SummaryCard
            label="Unhealthy"
            count={counts.unhealthy}
            state="unhealthy"
          />
          <SummaryCard label="Unknown" count={counts.unknown} state="unknown" />
        </div>

        {/* Error state */}
        {isError && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3.5 py-3 text-sm text-red-400">
            {error instanceof Error ? error.message : "Failed to load status."}
          </div>
        )}

        {/* Component placards */}
        {isLoading ? (
          <div className="space-y-2">
            {[...Array(4)].map((_, i) => (
              <div
                // biome-ignore lint/suspicious/noArrayIndexKey: skeleton placeholders have no identity
                key={i}
                className="h-14 rounded-xl bg-zinc-800/50 border border-zinc-700/50 animate-pulse"
              />
            ))}
          </div>
        ) : components.length === 0 ? (
          <p className="text-xs text-zinc-500 text-center py-6">
            No components returned by /v1/status
          </p>
        ) : (
          <div className="space-y-2">
            {components.map((comp) => (
              <ComponentCard key={comp.name} component={comp} />
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="shrink-0 flex items-center justify-between px-4 py-2.5 border-t border-zinc-700/60">
        <span className="text-xs text-zinc-500">
          {lastUpdated ? `Last updated: ${lastUpdated}` : "Loading…"}
        </span>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={isFetching}
          className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition-colors disabled:opacity-50"
        >
          <RefreshCw size={11} className={cn(isFetching && "animate-spin")} />
          Refresh All
        </button>
      </div>
    </div>
  );
}

// ─── floating trigger button ──────────────────────────────────────────────────

interface ConsoleStatusButtonProps {
  onClick: () => void;
  isOpen: boolean;
  overallStatus?: ComponentState;
}

export function ConsoleStatusButton({
  onClick,
  isOpen,
  overallStatus,
}: ConsoleStatusButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={isOpen}
      className={cn(
        "flex items-center gap-2 px-3 py-2 rounded-lg",
        "bg-zinc-800 border border-zinc-700 text-zinc-200 text-sm font-medium",
        "hover:bg-zinc-700 hover:border-zinc-600 transition-colors shadow-lg",
        isOpen && "bg-zinc-700 border-zinc-500",
      )}
    >
      <EvCharger size={14} className="shrink-0 text-zinc-400" />
      <span>Console Status</span>
      {overallStatus && (
        <span className="relative flex h-2 w-2 shrink-0">
          {overallStatus === "unhealthy" && (
            // Pulsing ring draws the eye to an outage; hidden under reduced motion.
            <span className="absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75 animate-ping motion-reduce:hidden" />
          )}
          <span
            className={cn(
              "relative inline-flex h-2 w-2 rounded-full",
              overallStatus === "healthy" && "bg-emerald-400",
              overallStatus === "degraded" && "bg-amber-400",
              overallStatus === "unhealthy" && "bg-red-400",
              overallStatus === "unknown" && "bg-zinc-400",
            )}
          />
        </span>
      )}
    </button>
  );
}
