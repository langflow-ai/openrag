"use client";

import { Wrench } from "lucide-react";
import { useComponentDiagnoseQuery } from "@/app/api/queries/useComponentActions";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface ComponentDiagnoseModalProps {
  component: string;
  displayName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ComponentDiagnoseModal({
  component,
  displayName,
  open,
  onOpenChange,
}: ComponentDiagnoseModalProps) {
  const { data, isLoading, isError, error } = useComponentDiagnoseQuery(
    open ? component : null,
  );

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
        ) : data ? (
          <div className="space-y-3 text-sm">
            <p className="text-zinc-100">{data.summary}</p>
            {data.likely_cause && (
              <div>
                <p className="text-[11px] uppercase tracking-wide text-zinc-500">
                  Likely cause
                </p>
                <p className="text-zinc-300 mt-0.5">{data.likely_cause}</p>
              </div>
            )}
            {data.remediation.length > 0 && (
              <div>
                <p className="text-[11px] uppercase tracking-wide text-zinc-500">
                  How to fix
                </p>
                <ul className="mt-1 space-y-1 list-disc list-inside text-zinc-300">
                  {data.remediation.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ul>
              </div>
            )}
            {data.target && (
              <p className="text-[11px] text-zinc-500">
                Endpoint: <span className="font-mono">{data.target}</span>
              </p>
            )}
            {data.last_error && (
              <pre className="text-[11px] text-zinc-400 bg-zinc-800/60 rounded p-2 whitespace-pre-wrap break-all font-mono">
                {data.last_error}
              </pre>
            )}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
