"use client";

import { AlertTriangle, Check, ChevronDown, RefreshCw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { KnowledgeUrlIcon } from "@/components/knowledge-url-icon";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

type Scope = "path" | "page" | "site";
type Form = {
  name: string;
  starting_url: string;
  scope: Scope;
  allow_subdomains: boolean;
  additional_hosts: string;
  include_paths: string;
  exclude_paths: string;
  max_pages: number;
  max_depth: number;
  max_downloaded_mb: number;
  max_crawl_minutes: number;
  resync_behavior: "full" | "root";
  removed_page_behavior: "retain" | "delete";
};
const INITIAL: Form = {
  name: "",
  starting_url: "",
  scope: "path",
  allow_subdomains: false,
  additional_hosts: "",
  include_paths: "",
  exclude_paths: "",
  max_pages: 250,
  max_depth: 4,
  max_downloaded_mb: 128,
  max_crawl_minutes: 15,
  resync_behavior: "full",
  removed_page_behavior: "retain",
};
const lines = (value: string) =>
  value.split("\n").flatMap((line) => {
    const trimmed = line.trim();
    return trimmed ? [trimmed] : [];
  });

function validUrl(value: string) {
  try {
    const url = new URL(value);
    return (
      ["http:", "https:"].includes(url.protocol) &&
      !url.username &&
      !url.password &&
      (!url.port || url.port === "80" || url.port === "443") &&
      !/^\d{1,3}(\.\d{1,3}){3}$/.test(url.hostname) &&
      !url.hostname.includes(":")
    );
  } catch {
    return false;
  }
}

function Choice({
  selected,
  onClick,
  title,
  detail,
}: {
  selected: boolean;
  onClick(): void;
  title: string;
  detail: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "min-h-24 flex-1 border p-4 text-left transition-colors",
        selected
          ? "border-primary bg-primary/5"
          : "border-border hover:bg-muted/50",
      )}
    >
      <p className="font-semibold">{title}</p>
      <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
    </button>
  );
}

export function UrlSourceDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange(open: boolean): void;
  onCreated?(taskId?: string): void;
}) {
  const [step, setStep] = useState(1);
  const [advanced, setAdvanced] = useState(false);
  const [pending, setPending] = useState(false);
  const [form, setForm] = useState<Form>(INITIAL);
  const update = <K extends keyof Form>(key: K, value: Form[K]) =>
    setForm((current) => ({ ...current, [key]: value }));
  const pageScope = form.scope === "page";
  const valid = Boolean(
    form.name.trim() &&
      validUrl(form.starting_url) &&
      lines(form.additional_hosts).every(
        (host) => !host.includes("/") && !/^\d{1,3}(\.\d{1,3}){3}$/.test(host),
      ) &&
      [...lines(form.include_paths), ...lines(form.exclude_paths)].every(
        (path) => path.startsWith("/"),
      ),
  );
  const close = (next: boolean) => {
    if (!next) {
      setStep(1);
      setAdvanced(false);
      setForm(INITIAL);
    }
    onOpenChange(next);
  };
  const submit = async () => {
    setPending(true);
    try {
      const response = await fetch("/api/connectors/url/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          additional_hosts: lines(form.additional_hosts),
          include_paths: lines(form.include_paths),
          exclude_paths: lines(form.exclude_paths),
          max_pages: pageScope ? 1 : form.max_pages,
          max_depth: pageScope ? 0 : form.max_depth,
        }),
      });
      const data = await response.json();
      if (!response.ok)
        throw new Error(
          data.detail || data.error || "Could not create website source",
        );
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
        <div
          className="-mx-6 grid shrink-0 grid-cols-2 border-y"
          role="group"
          aria-label="Website connection steps"
        >
          <button
            type="button"
            aria-current={step === 1 ? "step" : undefined}
            onClick={() => setStep(1)}
            className={cn(
              "flex w-full items-center gap-3 px-4 py-4 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:underline focus-visible:underline-offset-4",
              step === 1 && "border-b-2 border-b-primary",
            )}
          >
            <span
              className={cn(
                "flex size-7 items-center justify-center rounded-full text-sm",
                step > 1 && valid
                  ? "bg-green-500 text-white"
                  : step === 1
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground",
              )}
            >
              {step > 1 && valid ? (
                <Check className="size-4" />
              ) : (
                <KnowledgeUrlIcon className="size-4" />
              )}
            </span>
            <span className="font-medium">Source &amp; scope</span>
          </button>
          <button
            type="button"
            aria-current={step === 2 ? "step" : undefined}
            onClick={() => setStep(2)}
            className={cn(
              "flex w-full items-center gap-3 border-l px-4 py-4 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:underline focus-visible:underline-offset-4",
              step === 2 && "border-b-2 border-b-primary",
            )}
          >
            <span
              className={cn(
                "flex size-7 items-center justify-center rounded-full text-sm",
                step === 2
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground",
              )}
            >
              <RefreshCw className="size-4" />
            </span>
            <span className="font-medium">Re-sync behavior</span>
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {step === 1 ? (
            <div className="space-y-7 px-3 py-6">
              <div className="flex gap-3 border border-primary/30 bg-primary/5 p-4 text-sm">
                <AlertTriangle className="mt-0.5 size-5 shrink-0 text-primary" />
                <p>
                  URL ingestion always uses OpenRAG&apos;s native ingestion
                  pipeline, even when Langflow ingestion is enabled for other
                  sources.
                </p>
              </div>
              <div>
                <h3 className="text-lg font-semibold">
                  Where should we crawl?
                </h3>
                <p className="text-sm text-muted-foreground">
                  Give this connection a name and tell OpenRAG where to start.
                </p>
              </div>
              <div className="grid gap-5 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="url-name">Connection name</Label>
                  <Input
                    id="url-name"
                    value={form.name}
                    onChange={(e) => update("name", e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="url-start">Starting URL</Label>
                  <Input
                    id="url-start"
                    type="url"
                    placeholder="https://docs.example.com/guides/"
                    value={form.starting_url}
                    onChange={(e) => update("starting_url", e.target.value)}
                  />
                </div>
              </div>
              <div className="space-y-3">
                <div>
                  <Label>CRAWL SCOPE</Label>
                  <p className="text-sm text-muted-foreground">
                    How far should the crawler follow links from the starting
                    URL?
                  </p>
                </div>
                <div className="flex flex-col sm:flex-row">
                  <Choice
                    selected={form.scope === "path"}
                    onClick={() => update("scope", "path")}
                    title="Path and children"
                    detail="Follow approved pages beneath the starting path."
                  />
                  <Choice
                    selected={form.scope === "page"}
                    onClick={() => update("scope", "page")}
                    title="This page only"
                    detail="Ingest the starting page without following links."
                  />
                  <Choice
                    selected={form.scope === "site"}
                    onClick={() => update("scope", "site")}
                    title="Whole site"
                    detail="Follow approved pages anywhere on the site."
                  />
                </div>
              </div>
              <label className="flex items-center justify-between bg-muted/70 p-4">
                <span>
                  <span className="block font-medium">Allow subdomains</span>
                  <span className="text-sm text-muted-foreground">
                    Off by default. Every resolved destination must still be
                    public and in scope.
                  </span>
                </span>
                <input
                  type="checkbox"
                  checked={form.allow_subdomains}
                  onChange={(e) => update("allow_subdomains", e.target.checked)}
                  className="size-5 accent-primary"
                />
              </label>
              <button
                type="button"
                className="flex w-full items-center justify-between border-t pt-5 font-medium"
                onClick={() => setAdvanced((value) => !value)}
              >
                Advanced crawl settings{" "}
                <ChevronDown
                  className={cn(
                    "size-4 transition-transform",
                    advanced && "rotate-180",
                  )}
                />
              </button>
              {advanced && (
                <div className="space-y-5">
                  <div>
                    <h3 className="text-lg font-semibold">
                      Fine-tune the crawler
                    </h3>
                    <p className="text-sm text-muted-foreground">
                      Optional. Leave defaults unless you need precise control
                      over hosts, paths, or limits.
                    </p>
                  </div>
                  <div className="grid gap-5 sm:grid-cols-2">
                    <TextArea
                      label="Additional allowed hosts"
                      value={form.additional_hosts}
                      onChange={(v) => update("additional_hosts", v)}
                      placeholder="assets.example.com (one per line)"
                    />
                    <TextArea
                      label="Include paths"
                      value={form.include_paths}
                      onChange={(v) => update("include_paths", v)}
                      placeholder="/docs/ (one per line)"
                    />
                    <TextArea
                      label="Exclude paths"
                      value={form.exclude_paths}
                      onChange={(v) => update("exclude_paths", v)}
                      placeholder="/archive/ (one per line)"
                    />
                    <div className="space-y-2">
                      <Label>Change detection</Label>
                      <div className="flex h-10 items-center bg-muted px-3 text-sm">
                        Normalized content hash
                      </div>
                    </div>
                    {(
                      [
                        ["max_pages", "Maximum pages"],
                        ["max_depth", "Maximum depth"],
                        ["max_downloaded_mb", "Maximum downloaded MB"],
                        ["max_crawl_minutes", "Maximum crawl minutes"],
                      ] as const
                    ).map(([key, label]) => (
                      <div key={key} className="space-y-2">
                        <Label>{label}</Label>
                        <Input
                          type="number"
                          min={0}
                          disabled={
                            pageScope &&
                            (key === "max_pages" || key === "max_depth")
                          }
                          value={
                            pageScope && key === "max_pages"
                              ? 1
                              : pageScope && key === "max_depth"
                                ? 0
                                : form[key]
                          }
                          onChange={(e) => update(key, Number(e.target.value))}
                        />
                      </div>
                    ))}
                  </div>
                  <div className="flex gap-3 border border-green-500/40 bg-green-500/10 p-4 text-sm">
                    <Check className="size-5 shrink-0 text-green-600" />
                    <p>
                      <strong>Always-on safety</strong>
                      <br />
                      OpenRAG identifies itself, honors robots.txt, restricts
                      redirects and approved hosts, blocks private/internal
                      destinations, limits crawl size and time, and runs
                      asynchronously within OpenRAG&apos;s task system. These
                      controls cannot be disabled.
                    </p>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-8 px-3 py-6">
              <div>
                <h3 className="text-lg font-semibold">
                  How should re-syncs work?
                </h3>
                <p className="text-sm text-muted-foreground">
                  Choose what happens when OpenRAG revisits this website.
                </p>
              </div>
              <div className="space-y-3">
                <div>
                  <Label>RE-SYNC BEHAVIOR</Label>
                  <p className="text-sm text-muted-foreground">
                    When a scheduled or manual re-crawl runs, which pages get
                    ingested?
                  </p>
                </div>
                <div className="flex flex-col sm:flex-row">
                  <Choice
                    selected={form.resync_behavior === "full"}
                    onClick={() => update("resync_behavior", "full")}
                    title="Full crawl; ingest returned pages"
                    detail="Repeat the saved crawl scope and reconcile returned pages."
                  />
                  <Choice
                    selected={form.resync_behavior === "root"}
                    onClick={() => update("resync_behavior", "root")}
                    title="Ingest only root page"
                    detail="Update the starting page and leave existing children unchanged."
                  />
                </div>
              </div>
              <div className="space-y-3">
                <div>
                  <Label>REMOVED PAGES</Label>
                  <p className="text-sm text-muted-foreground">
                    What should happen to pages that disappear from the site?
                  </p>
                </div>
                <div className="flex flex-col sm:flex-row">
                  <Choice
                    selected={form.removed_page_behavior === "retain"}
                    onClick={() => update("removed_page_behavior", "retain")}
                    title="Retain in corpus"
                    detail="Keep the last indexed copy when a page disappears."
                  />
                  <Choice
                    selected={form.removed_page_behavior === "delete"}
                    onClick={() => update("removed_page_behavior", "delete")}
                    title="Delete"
                    detail="Delete pages absent from a complete, successful full crawl."
                  />
                </div>
                <p className="text-sm text-muted-foreground">
                  Incomplete or capped crawls never delete missing pages.
                </p>
              </div>
            </div>
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

function TextArea({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange(value: string): void;
  placeholder: string;
}) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <textarea
        className="min-h-20 w-full bg-muted px-3 py-2 text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}
