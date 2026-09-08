"use client";

import {
  ChevronDown,
  ChevronUp,
  RefreshCw,
  ScrollText,
  TrendingUp,
  Wrench,
} from "lucide-react";
import { type ReactNode, useCallback, useState } from "react";
import { toast } from "sonner";
import { useComponentSyncMutation } from "@/app/api/queries/useComponentActions";
import type { ComponentStatus } from "@/app/api/queries/useConsoleStatusQuery";
import { formatRelative, statusTokens } from "@/lib/status-utils";
import { cn } from "@/lib/utils";
import { ComponentDiagnoseModal } from "./diagnose-modal";
import { ComponentLogsModal } from "./logs-modal";
import { StatusIcon } from "./status-icon";

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

function ComponentCardDetails({
  component,
  isRealComponent,
  syncing,
  onLogsOpen,
  onDebugOpen,
  onSync,
}: {
  component: ComponentStatus;
  isRealComponent: boolean;
  syncing: boolean;
  onLogsOpen: () => void;
  onDebugOpen: () => void;
  onSync: () => void;
}) {
  const { latency_ms, build, metadata, checked_at } = component;

  const hasBuildDetails =
    build &&
    (build.git_sha || build.build_time || build.image || build.image_digest);
  const hasMetadata = metadata && Object.keys(metadata).length > 0;

  return (
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
        <MetaRow label="Digest" value={`${build.image_digest.slice(0, 20)}…`} />
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

      {isRealComponent && (
        <div className="flex items-center justify-between gap-2 pt-2">
          <ActionButton
            icon={<Wrench size={14} />}
            ariaLabel="Debug this component"
            onClick={onDebugOpen}
          />
          <div className="flex items-center gap-1.5">
            <ActionButton
              icon={<ScrollText size={13} />}
              label="Logs"
              onClick={onLogsOpen}
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
              onClick={onSync}
            />
          </div>
        </div>
      )}
    </div>
  );
}

export function ComponentCard({ component }: { component: ComponentStatus }) {
  const [expanded, setExpanded] = useState(false);
  const [logsOpen, setLogsOpen] = useState(false);
  const [debugOpen, setDebugOpen] = useState(false);

  const isRealComponent = component.name !== "providers";
  const { mutate, isPending, variables } = useComponentSyncMutation();
  const syncing = isPending && variables === component.name;

  const handleSync = useCallback(() => {
    mutate(component.name, {
      onError: (err) => {
        toast.error(
          `Sync failed: ${err instanceof Error ? err.message : "unknown error"}`,
        );
      },
    });
  }, [mutate, component.name]);

  const { display_name, status, version, latency_ms, message } = component;

  return (
    <div
      className={cn(
        "rounded-xl border bg-zinc-800/60 transition-colors",
        expanded ? "border-zinc-600/70" : "border-zinc-700/50",
      )}
    >
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
                statusTokens(status).badge,
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

      {expanded && (
        <ComponentCardDetails
          component={component}
          isRealComponent={isRealComponent}
          syncing={syncing}
          onLogsOpen={() => setLogsOpen(true)}
          onDebugOpen={() => setDebugOpen(true)}
          onSync={handleSync}
        />
      )}

      {isRealComponent && logsOpen && (
        <ComponentLogsModal
          component={component.name}
          displayName={display_name}
          open={logsOpen}
          onOpenChange={setLogsOpen}
        />
      )}
      {isRealComponent && debugOpen && (
        <ComponentDiagnoseModal
          component={component.name}
          displayName={display_name}
          open={debugOpen}
          onOpenChange={setDebugOpen}
        />
      )}
    </div>
  );
}
