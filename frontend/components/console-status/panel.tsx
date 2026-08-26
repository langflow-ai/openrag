"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { EvCharger, RefreshCw, XCircle } from "lucide-react";
import { useLayoutEffect, useState } from "react";
import {
  type ComponentStatus,
  useConsoleStatusQuery,
} from "@/app/api/queries/useConsoleStatusQuery";
import { useProviderHealthQuery } from "@/app/api/queries/useProviderHealthQuery";
import { Dialog, DialogPortal, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { HEADER_HEIGHT } from "@/lib/constants";
import { statusTokens } from "@/lib/status-utils";
import { cn } from "@/lib/utils";
import { ComponentCard } from "./component-card";
import { providerHealthToComponent } from "./provider-health";
import { refreshConsoleStatusQueries } from "./refresh";

/** Gap between the bottom of banners+header and the floating panel. */
const PANEL_GAP_PX = 10;

/** Bottom of the banners+header block in viewport pixels. Health banners sit
 *  above the header, so HEADER_HEIGHT from the viewport top is wrong. */
function useTopChromeBottom() {
  const [bottom, setBottom] = useState(HEADER_HEIGHT);

  useLayoutEffect(() => {
    const chrome = document.getElementById("app-top-chrome");
    if (!chrome) return;

    const update = () => {
      setBottom(chrome.getBoundingClientRect().bottom);
    };
    update();

    const observer = new ResizeObserver(update);
    observer.observe(chrome);
    window.addEventListener("resize", update);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", update);
    };
  }, []);

  return bottom;
}

function SummaryCard({
  label,
  count,
  state,
}: {
  label: string;
  count: number;
  state: ComponentStatus["status"];
}) {
  const { text } = statusTokens(state);
  return (
    <div className="flex-1 rounded-lg bg-zinc-800/60 border border-zinc-700/50 px-3 py-2.5">
      <p className="text-[11px] font-medium text-zinc-400 uppercase tracking-wide">
        {label}
      </p>
      <p className={cn("text-2xl font-semibold mt-0.5", text)}>{count}</p>
    </div>
  );
}

function countByState(components: ComponentStatus[]) {
  const counts = { healthy: 0, degraded: 0, unhealthy: 0, unknown: 0 };
  for (const component of components) {
    counts[component.status] += 1;
  }
  return counts;
}

interface ConsoleStatusPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export function ConsoleStatusPanel({
  isOpen,
  onClose,
}: ConsoleStatusPanelProps) {
  const {
    data,
    isLoading,
    isFetching,
    isError,
    error,
    refetch,
    dataUpdatedAt,
  } = useConsoleStatusQuery();

  // Same cache as the provider-health banner — no extra round-trip.
  const {
    data: providerHealth,
    refetch: refetchProviderHealth,
    isFetching: isProviderFetching,
    dataUpdatedAt: providerUpdatedAt,
    isEnabled: isProviderQueryEnabled,
  } = useProviderHealthQuery();

  const backendComponents = Array.isArray(data?.components)
    ? data.components
    : [];
  const components = providerHealth
    ? [...backendComponents, providerHealthToComponent(providerHealth)]
    : backendComponents;

  const counts = countByState(components);
  const isRefreshing = isFetching || isProviderFetching;
  const lastUpdatedAt = Math.max(dataUpdatedAt, providerUpdatedAt);
  const lastUpdated = lastUpdatedAt
    ? new Date(lastUpdatedAt).toLocaleTimeString()
    : null;

  const chromeBottom = useTopChromeBottom();
  const overlayTop = chromeBottom;
  const panelTop = chromeBottom + PANEL_GAP_PX;

  return (
    <Dialog
      // Non-modal: a modal dialog disables pointer events on the header, so
      // the trigger never receives the click that should collapse the panel.
      modal={false}
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogPortal>
        {/* Starts below banners+header so the trigger stays clickable even
            when health banners push the header down. Animate-out keeps it
            mounted through pointerup so a dismiss click does not fall through. */}
        <DialogPrimitive.Overlay
          className={cn(
            "fixed inset-x-0 bottom-0 z-40 bg-transparent",
            "data-[state=open]:animate-in data-[state=closed]:animate-out",
            "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
            "duration-150",
          )}
          style={{ top: overlayTop }}
        />
        <DialogPrimitive.Content
          id="console-status-panel"
          aria-describedby={undefined}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            document.getElementById("console-status-trigger")?.focus();
          }}
          onInteractOutside={(event) => {
            const target = event.target as HTMLElement | null;
            // Let the trigger's onClick toggle-close; if Dialog also dismisses
            // on pointerdown the following click reopens the panel.
            if (
              target?.closest("#console-status-trigger") ||
              target?.closest("[data-slot='dialog-content']") ||
              target?.closest("[data-slot='dialog-overlay']")
            ) {
              event.preventDefault();
            }
          }}
          className={cn(
            "fixed right-6 z-40",
            "w-[440px] flex flex-col",
            "bg-zinc-900 border border-zinc-700/70 rounded-2xl shadow-2xl overflow-hidden",
            "outline-none",
          )}
          style={{
            top: panelTop,
            maxHeight: `calc(100vh - ${panelTop}px - 2rem)`,
          }}
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700/60 shrink-0">
            <div className="flex items-center gap-2">
              <EvCharger size={15} className="text-zinc-400" />
              <DialogTitle className="text-sm font-semibold text-zinc-100">
                Console Status
              </DialogTitle>
              {isRefreshing && (
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

          <div className="flex-1 overflow-y-auto scrollbar-hide px-4 py-3 space-y-3">
            <div className="grid grid-cols-4 gap-2">
              <SummaryCard
                label="Healthy"
                count={counts.healthy}
                state="healthy"
              />
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
              <SummaryCard
                label="Unknown"
                count={counts.unknown}
                state="unknown"
              />
            </div>

            {isError && (
              <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3.5 py-3 text-sm text-red-400">
                {error instanceof Error
                  ? error.message
                  : "Failed to load status."}
              </div>
            )}

            {isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 4 }, (_, i) => (
                  <Skeleton
                    key={i}
                    className="h-14 rounded-xl bg-zinc-800/50 border border-zinc-700/50"
                  />
                ))}
              </div>
            ) : components.length === 0 ? (
              <p className="text-xs text-zinc-500 text-center py-6">
                No components returned by status API.
              </p>
            ) : (
              <div className="space-y-2">
                {components.map((comp) => (
                  <ComponentCard key={comp.name} component={comp} />
                ))}
              </div>
            )}
          </div>

          <div className="shrink-0 flex items-center justify-between px-4 py-2.5 border-t border-zinc-700/60">
            <span className="text-xs text-zinc-500">
              {lastUpdated ? `Last updated: ${lastUpdated}` : "Loading…"}
            </span>
            <button
              type="button"
              onClick={() => {
                refreshConsoleStatusQueries(
                  refetch,
                  refetchProviderHealth,
                  isProviderQueryEnabled,
                );
              }}
              disabled={isRefreshing}
              className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition-colors disabled:opacity-50"
            >
              <RefreshCw
                size={11}
                className={cn(isRefreshing && "animate-spin")}
              />
              Refresh All
            </button>
          </div>
        </DialogPrimitive.Content>
      </DialogPortal>
    </Dialog>
  );
}
