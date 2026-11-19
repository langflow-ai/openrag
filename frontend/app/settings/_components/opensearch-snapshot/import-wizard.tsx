"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { ImportProgressStep } from "./import-progress-step";
import { PreflightStep } from "./preflight-step";
import { SnapshotStep } from "./snapshot-step";
import { SourceStep } from "./source-step";

type WizardStep = "source" | "snapshot" | "preflight" | "import";

const STEPS: { id: WizardStep; label: string }[] = [
  { id: "source", label: "Source" },
  { id: "snapshot", label: "Snapshot" },
  { id: "preflight", label: "Preflight" },
  { id: "import", label: "Datasets" },
];

interface ImportWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Open an existing import (e.g. one waiting in `review`) instead of a new one. */
  resumeImportId?: string | null;
  pollIntervalMs?: number;
}

function WizardBody({
  resumeImportId,
  pollIntervalMs,
  onClose,
}: {
  resumeImportId: string | null;
  pollIntervalMs?: number;
  onClose: () => void;
}) {
  const [step, setStep] = useState<WizardStep>(
    resumeImportId ? "import" : "source",
  );
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<string | null>(null);
  const [indices, setIndices] = useState<string[]>([]);
  const [importId, setImportId] = useState<string | null>(resumeImportId);
  const currentIndex = STEPS.findIndex((s) => s.id === step);

  return (
    <>
      <ol
        aria-label="Import steps"
        className="flex shrink-0 gap-4 border-y px-6 py-3 text-sm"
      >
        {STEPS.map((s, index) => (
          <li
            key={s.id}
            aria-current={s.id === step ? "step" : undefined}
            className={cn(
              "text-muted-foreground",
              index === currentIndex && "font-semibold text-foreground",
            )}
          >
            {index + 1}. {s.label}
          </li>
        ))}
      </ol>
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        {step === "source" && (
          <SourceStep
            selectedId={sourceId}
            onSelect={setSourceId}
            onContinue={() => setStep("snapshot")}
          />
        )}
        {step === "snapshot" && sourceId && (
          <SnapshotStep
            sourceId={sourceId}
            snapshotName={snapshot}
            indices={indices}
            onChange={(name, next) => {
              setSnapshot(name);
              setIndices(next);
            }}
            onBack={() => setStep("source")}
            onContinue={() => setStep("preflight")}
          />
        )}
        {step === "preflight" && sourceId && snapshot && (
          <PreflightStep
            sourceId={sourceId}
            snapshot={snapshot}
            indices={indices}
            onBack={() => setStep("snapshot")}
            onStarted={(id) => {
              setImportId(id);
              setStep("import");
            }}
          />
        )}
        {step === "import" && importId && (
          <ImportProgressStep
            importId={importId}
            pollIntervalMs={pollIntervalMs}
            onDone={onClose}
          />
        )}
      </div>
    </>
  );
}

export function ImportWizard({
  open,
  onOpenChange,
  resumeImportId = null,
  pollIntervalMs,
}: ImportWizardProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[92vh] max-w-3xl flex-col gap-0 overflow-hidden !p-0 sm:rounded-lg">
        <DialogHeader className="shrink-0 px-6 py-6 pr-14">
          <DialogTitle className="text-2xl">
            Import an OpenSearch snapshot
          </DialogTitle>
          <DialogDescription>
            Restore indices from a snapshot in S3 as searchable datasets.
          </DialogDescription>
        </DialogHeader>
        {/* Mounted only while open so every close resets the wizard. */}
        {open && (
          <WizardBody
            resumeImportId={resumeImportId}
            pollIntervalMs={pollIntervalMs}
            onClose={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
