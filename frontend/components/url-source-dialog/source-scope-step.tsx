import { AlertTriangle, ChevronDown } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { AdvancedCrawlSettings } from "./advanced-crawl-settings";
import { Choice } from "./choice";
import type { UpdateUrlSourceForm, UrlSourceForm } from "./form";

export function SourceScopeStep({
  form,
  advanced,
  onAdvancedChange,
  onUpdate,
}: {
  form: UrlSourceForm;
  advanced: boolean;
  onAdvancedChange(open: boolean): void;
  onUpdate: UpdateUrlSourceForm;
}) {
  return (
    <div className="space-y-7 px-3 py-6">
      <div className="flex gap-3 border border-primary/30 bg-primary/5 p-4 text-sm">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-primary" />
        <p>
          URL ingestion always uses OpenRAG&apos;s native ingestion pipeline,
          even when Langflow ingestion is enabled for other sources.
        </p>
      </div>
      <div>
        <h3 className="text-lg font-semibold">Where should we crawl?</h3>
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
            onChange={(event) => onUpdate("name", event.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="url-start">Starting URL</Label>
          <Input
            id="url-start"
            type="url"
            placeholder="https://docs.example.com/guides/"
            value={form.starting_url}
            onChange={(event) => onUpdate("starting_url", event.target.value)}
          />
        </div>
      </div>
      <div className="space-y-3">
        <div>
          <Label>CRAWL SCOPE</Label>
          <p className="text-sm text-muted-foreground">
            How far should the crawler follow links from the starting URL?
          </p>
        </div>
        <div className="flex flex-col sm:flex-row">
          <Choice
            selected={form.scope === "path"}
            onClick={() => onUpdate("scope", "path")}
            title="Path and children"
            detail="Follow approved pages beneath the starting path."
          />
          <Choice
            selected={form.scope === "page"}
            onClick={() => onUpdate("scope", "page")}
            title="This page only"
            detail="Ingest the starting page without following links."
          />
          <Choice
            selected={form.scope === "site"}
            onClick={() => onUpdate("scope", "site")}
            title="Whole site"
            detail="Follow approved pages anywhere on the site."
          />
        </div>
      </div>
      <label className="flex items-center justify-between bg-muted/70 p-4">
        <span>
          <span className="block font-medium">Allow subdomains</span>
          <span className="text-sm text-muted-foreground">
            Off by default. Every resolved destination must still be public and
            in scope.
          </span>
        </span>
        <input
          type="checkbox"
          checked={form.allow_subdomains}
          onChange={(event) =>
            onUpdate("allow_subdomains", event.target.checked)
          }
          className="size-5 accent-primary"
        />
      </label>
      <button
        type="button"
        className="flex w-full items-center justify-between border-t pt-5 font-medium"
        onClick={() => onAdvancedChange(!advanced)}
      >
        Advanced crawl settings
        <ChevronDown
          className={cn(
            "size-4 transition-transform",
            advanced && "rotate-180",
          )}
        />
      </button>
      {advanced && <AdvancedCrawlSettings form={form} onUpdate={onUpdate} />}
    </div>
  );
}
