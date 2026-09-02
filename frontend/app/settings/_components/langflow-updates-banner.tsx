"use client";

import { AlertTriangle, X } from "lucide-react";
import { useState } from "react";
import { useGetFlowsUpdatesQuery } from "@/app/api/queries/useGetFlowsUpdatesQuery";
import { FlowsUpdateDialog } from "@/components/flows-update-dialog";
import { useAuth } from "@/contexts/auth-context";
import { useBrand } from "@/contexts/brand-context";
import { usePermissions } from "@/hooks/use-permissions";
import { cn } from "@/lib/utils";

export function LangflowUpdatesBanner() {
  const { brand } = useBrand();
  const isIbm = brand === "ibm";
  const { can } = usePermissions();
  const canEdit = can("config:write");
  const { data: updates, isLoading } = useGetFlowsUpdatesQuery({
    enabled: canEdit,
  });
  const [isDismissed, setIsDismissed] = useState(false);
  const [showModal, setShowModal] = useState(false);

  const hasUpdates = (updates?.length ?? 0) > 0;

  if (!canEdit || isLoading || !updates || !hasUpdates || isDismissed) {
    return null;
  }

  return (
    <>
      <div
        className={cn(
          "mb-6 border border-brand-amber-30 text-foreground px-4 py-3 text-sm",
          isIbm
            ? "bg-card border-l-4 border-l-brand-amber rounded-none"
            : "bg-brand-amber-10 rounded-lg",
        )}
      >
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            {isIbm ? (
              <div className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-brand-amber text-card">
                <span className="font-bold text-xs">!</span>
              </div>
            ) : (
              <AlertTriangle className="h-5 w-5 shrink-0 text-brand-amber" />
            )}
            <div className="truncate">
              <span className="font-semibold text-foreground">
                Langflow flow updates available
              </span>
              <span className="text-muted-foreground ml-2 hidden sm:inline text-mmd">
                New versions of one or more Langflow flows are available.
              </span>
            </div>
          </div>
          <div className="flex items-center gap-4 shrink-0">
            <button
              type="button"
              onClick={() => setShowModal(true)}
              className={cn(
                "hover:underline font-medium text-sm bg-transparent border-0 cursor-pointer p-0",
                isIbm ? "text-[#78a9ff]" : "text-primary",
              )}
            >
              View update details
            </button>
            <button
              type="button"
              onClick={() => setIsDismissed(true)}
              aria-label="Dismiss banner"
              className="text-muted-foreground hover:text-foreground bg-transparent border-0 cursor-pointer p-1"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {showModal && (
        <FlowsUpdateDialog overrideOpen={true} onOpenChange={setShowModal} />
      )}
    </>
  );
}
