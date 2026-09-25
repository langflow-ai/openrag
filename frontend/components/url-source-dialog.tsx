"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  createUrlSourcePayload,
  INITIAL_URL_SOURCE_FORM,
  isUrlSourceFormValid,
  type UrlSourceForm,
} from "./url-source-dialog/form";
import { ResyncBehaviorStep } from "./url-source-dialog/resync-behavior-step";
import { SourceScopeStep } from "./url-source-dialog/source-scope-step";
import {
  type UrlSourceDialogStep,
  UrlSourceDialogTabs,
} from "./url-source-dialog/tabs";

export function UrlSourceDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange(open: boolean): void;
  onCreated?(taskId?: string): void;
}) {
  const [step, setStep] = useState<UrlSourceDialogStep>(1);
  const [advanced, setAdvanced] = useState(false);
  const [pending, setPending] = useState(false);
  const [form, setForm] = useState<UrlSourceForm>(INITIAL_URL_SOURCE_FORM);

  const update = <K extends keyof UrlSourceForm>(
    key: K,
    value: UrlSourceForm[K],
  ) => setForm((current) => ({ ...current, [key]: value }));
  const valid = isUrlSourceFormValid(form);

  const close = (next: boolean) => {
    if (!next) {
      setStep(1);
      setAdvanced(false);
      setForm(INITIAL_URL_SOURCE_FORM);
    }
    onOpenChange(next);
  };

  const submit = async () => {
    setPending(true);
    try {
      const response = await fetch("/api/connectors/url/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(createUrlSourcePayload(form)),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(
          data.detail || data.error || "Could not create website source",
        );
      }
      onCreated?.(data.last_task_id);
      close(false);
      toast.success("Website crawl started");
    } catch (error) {
      toast.error("Could not start website crawl", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="flex max-h-[92vh] max-w-4xl flex-col gap-0 overflow-hidden !p-0 sm:rounded-lg">
        <DialogHeader className="shrink-0 px-6 py-6 pr-14">
          <DialogTitle className="text-2xl">
            Add a Website connection
          </DialogTitle>
          <DialogDescription>
            Crawl public website content into OpenRAG.
          </DialogDescription>
        </DialogHeader>
        <UrlSourceDialogTabs
          step={step}
          sourceComplete={valid}
          onStepChange={setStep}
        />
        <div className="min-h-0 flex-1 overflow-y-auto">
          {step === 1 ? (
            <SourceScopeStep
              form={form}
              advanced={advanced}
              onAdvancedChange={setAdvanced}
              onUpdate={update}
            />
          ) : (
            <ResyncBehaviorStep form={form} onUpdate={update} />
          )}
        </div>
        <div className="flex shrink-0 justify-end gap-3 border-t bg-background px-6 py-4">
          <Button variant="outline" onClick={() => close(false)}>
            Cancel
          </Button>
          <Button
            disabled={!valid || pending}
            onClick={() => (step === 1 ? setStep(2) : submit())}
          >
            {pending ? "Starting…" : step === 1 ? "Continue" : "Ingest URL"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
