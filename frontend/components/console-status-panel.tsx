"use client";

import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  EvCharger,
  HelpCircle,
  RefreshCw,
  ScrollText,
  TrendingUp,
  Wrench,
  XCircle,
} from "lucide-react";
import { type ReactNode, useCallback, useState } from "react";
import {
  type DiagnosisResponse,
  useComponentDiagnoseQuery,
  useComponentSyncMutation,
} from "@/app/api/queries/useComponentActions";
import {
  type LogEntry,
  useComponentLogsQuery,
} from "@/app/api/queries/useComponentLogsQuery";
import {
  type ComponentState,
  type ComponentStatus,
  useConsoleStatusQuery,
} from "@/app/api/queries/useConsoleStatusQuery";
import {
  type ProviderHealthResponse,
  useProviderHealthQuery,
} from "@/app/api/queries/useProviderHealthQuery";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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

// ─── action button ────────────────────────────────────────────────────────────

/** Compact card action. Icon-only when `label` is omitted (uses `ariaLabel`). */
function ActionButton({
  icon,
  label,
  ariaLabel,
  disabled,
  onClick,
}: {
  icon: ReactNode;
  label?: string;
  ariaLabel?: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel ?? label}
      title={ariaLabel ?? label}
      className={cn(
        "flex items-center gap-1.5 rounded text-xs font-medium",
        label ? "px-2.5 py-1" : "p-1.5",
        "bg-zinc-700/60 border border-zinc-600/60 text-zinc-200",
        "hover:bg-zinc-600/60 hover:border-zinc-500/60 transition-colors",
        "disabled:opacity-50 disabled:cursor-not-allowed",
      )}
    >
      <span className="shrink-0">{icon}</span>
      {label}
    </button>
  );
}

/** "just now" / "5 minutes ago" from an ISO-8601 timestamp. */
function formatRelative(iso?: string | null): string {
  if (!iso) return "—";
  const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (!Number.isFinite(secs) || secs < 0) return "just now";
  if (secs < 45) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} minute${mins === 1 ? "" : "s"} ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hour${hrs === 1 ? "" : "s"} ago`;
  const days = Math.round(hrs / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

// ─── log level helpers ────────────────────────────────────────────────────────

function logLevelColor(level: string) {
  switch (level.toLowerCase()) {
    case "error":
    case "critical":
      return "text-red-400";
    case "warning":
      return "text-amber-400";
    case "info":
      return "text-sky-400";
    default:
      return "text-zinc-400";
  }
}

// ─── component logs modal ─────────────────────────────────────────────────────

interface ComponentLogsModalProps {
  component: string;
  displayName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function ComponentLogsModal({
  component,
  displayName,
  open,
  onOpenChange,
}: ComponentLogsModalProps) {
  const { data, isLoading, isError, error, refetch, isFetching } =
    useComponentLogsQuery(open ? component : null, 100);

  const entries: LogEntry[] = data?.entries ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "bg-zinc-900 border-zinc-700 text-zinc-100",
          "w-[560px] max-w-[95vw] max-h-[70vh] flex flex-col gap-0 p-0",
        )}
      >
        {/* Modal header */}
        <DialogHeader className="shrink-0 flex flex-row items-center justify-between pl-4 pr-10 py-3 border-b border-zinc-700/60">
          <div className="flex items-center gap-2">
            <ScrollText size={14} className="text-zinc-400" />
            <DialogTitle className="text-sm font-semibold text-zinc-100">
              {displayName} — Logs
            </DialogTitle>
            {isFetching && (
              <RefreshCw size={11} className="text-zinc-500 animate-spin" />
            )}
          </div>
          <button
            type="button"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors disabled:opacity-40"
          >
            Refresh
          </button>
        </DialogHeader>

        {/* Log list */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-1.5 min-h-0">
          {isLoading ? (
            <div className="space-y-1.5">
              {[...Array(5)].map((_, i) => (
                <div
                  // biome-ignore lint/suspicious/noArrayIndexKey: skeleton placeholders
                  key={i}
                  className="h-8 rounded bg-zinc-800/60 animate-pulse"
                />
              ))}
            </div>
          ) : isError ? (
            <p className="text-sm text-red-400">
              {error instanceof Error ? error.message : "Failed to load logs."}
            </p>
          ) : entries.length === 0 ? (
            <p className="text-xs text-zinc-500 italic text-center py-6">
              No log entries recorded yet.
            </p>
          ) : (
            entries.map((entry, idx) => (
              <div
                // biome-ignore lint/suspicious/noArrayIndexKey: log entries have no stable id
                key={idx}
                className="rounded bg-zinc-800/50 border border-zinc-700/40 px-2.5 py-1.5"
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className={cn(
                      "text-[10px] font-semibold uppercase tabular-nums shrink-0",
                      logLevelColor(entry.level),
                    )}
                  >
                    {entry.level}
                  </span>
                  <span className="text-[10px] text-zinc-500 tabular-nums shrink-0">
                    {new Date(entry.timestamp).toLocaleTimeString()}
                  </span>
                  <span className="text-xs text-zinc-200 break-all">
                    {entry.message}
                  </span>
                </div>
                {entry.detail && (
                  <p className="text-[11px] text-zinc-400 mt-0.5 ml-0 break-all font-mono">
                    {entry.detail}
                  </p>
                )}
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="shrink-0 px-4 py-2 border-t border-zinc-700/60">
          <span className="text-[11px] text-zinc-500">
            {entries.length} entr{entries.length === 1 ? "y" : "ies"} (most
            recent 100)
          </span>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ─── diagnostics modal ────────────────────────────────────────────────────────

interface ComponentDiagnoseModalProps {
  component: string;
  displayName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function ComponentDiagnoseModal({
  component,
  displayName,
  open,
  onOpenChange,
}: ComponentDiagnoseModalProps) {
  const { data, isLoading, isError, error } = useComponentDiagnoseQuery(
    open ? component : null,
  );
  const d: DiagnosisResponse | undefined = data;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-zinc-900 border-zinc-700 text-zinc-100 w-[520px] max-w-[95vw]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-sm font-semibold">
            <Wrench size={14} className="text-zinc-400" />
            {displayName} — Debug
          </DialogTitle>
        </DialogHeader>

        {isLoading ? (
          <div className="h-24 rounded bg-zinc-800/60 animate-pulse" />
        ) : isError ? (
          <p className="text-sm text-red-400">
            {error instanceof Error ? error.message : "Failed to diagnose."}
          </p>
        ) : d ? (
          <div className="space-y-3 text-sm">
            <p className="text-zinc-100">{d.summary}</p>
            {d.likely_cause && (
              <div>
                <p className="text-[11px] uppercase tracking-wide text-zinc-500">
                  Likely cause
                </p>
                <p className="text-zinc-300 mt-0.5">{d.likely_cause}</p>
              </div>
            )}
            {d.remediation.length > 0 && (
              <div>
                <p className="text-[11px] uppercase tracking-wide text-zinc-500">
                  How to fix
                </p>
                <ul className="mt-1 space-y-1 list-disc list-inside text-zinc-300">
                  {d.remediation.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ul>
              </div>
            )}
            {d.target && (
              <p className="text-[11px] text-zinc-500">
                Endpoint: <span className="font-mono">{d.target}</span>
              </p>
            )}
            {d.last_error && (
              <pre className="text-[11px] text-zinc-400 bg-zinc-800/60 rounded p-2 whitespace-pre-wrap break-all font-mono">
                {d.last_error}
              </pre>
            )}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

// ─── component placard ───────────────────────────────────────────────────────

interface ComponentCardProps {
  component: ComponentStatus;
}

function ComponentCard({ component }: ComponentCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [logsOpen, setLogsOpen] = useState(false);
  const [debugOpen, setDebugOpen] = useState(false);

  // The synthetic "providers" card is not a real component — no actions.
  const isRealComponent = component.name !== "providers";

  const syncMutation = useComponentSyncMutation();
  const syncing =
    syncMutation.isPending && syncMutation.variables === component.name;

  const {
    display_name,
    status,
    version,
    latency_ms,
    message,
    build,
    metadata,
    checked_at,
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
          {isRealComponent && (
            <>
              <MetaRow label="Last Sync" value={formatRelative(checked_at)} />
              <div className="flex items-center justify-between gap-2 py-1">
                <span className="text-xs text-zinc-500 shrink-0">
                  Response Time
                </span>
                <span className="flex items-center gap-1 text-xs text-zinc-300 tabular-nums">
                  <TrendingUp size={12} className="text-emerald-400" />
                  {latency_ms != null ? `${latency_ms}ms` : "—"}
                </span>
              </div>
            </>
          )}
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
          {hasMetadata
            ? Object.entries(metadata).map(([k, v]) => (
                <MetaRow key={k} label={k} value={String(v)} />
              ))
            : null}
          {!isRealComponent && !hasBuildDetails && !hasMetadata && (
            <p className="text-xs text-zinc-500 italic">
              No additional details available.
            </p>
          )}

          {/* Action row — not shown for the synthetic Model Providers card */}
          {isRealComponent && (
            <div className="flex items-center justify-between gap-2 pt-2">
              <ActionButton
                icon={<Wrench size={14} />}
                ariaLabel="Debug this component"
                onClick={() => setDebugOpen(true)}
              />
              <div className="flex items-center gap-1.5">
                <ActionButton
                  icon={<ScrollText size={13} />}
                  label="Logs"
                  onClick={() => setLogsOpen(true)}
                />
                <ActionButton
                  icon={
                    <RefreshCw
                      size={13}
                      className={cn(syncing && "animate-spin")}
                    />
                  }
                  label="Sync"
                  disabled={syncing}
                  onClick={() => syncMutation.mutate(component.name)}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Modals */}
      {isRealComponent && (
        <>
          <ComponentLogsModal
            component={component.name}
            displayName={display_name}
            open={logsOpen}
            onOpenChange={setLogsOpen}
          />
          <ComponentDiagnoseModal
            component={component.name}
            displayName={display_name}
            open={debugOpen}
            onOpenChange={setDebugOpen}
          />
        </>
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
  const { data: providerHealth } = useProviderHealthQuery();

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
