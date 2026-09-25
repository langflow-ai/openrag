import { Info } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { UpdateUrlSourceForm, UrlSourceForm } from "./form";

export function AdvancedCrawlSettings({
  form,
  onUpdate,
}: {
  form: UrlSourceForm;
  onUpdate: UpdateUrlSourceForm;
}) {
  const pageScope = form.scope === "page";

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-lg font-semibold">Fine-tune the crawler</h3>
        <p className="text-sm text-muted-foreground">
          Optional. Leave defaults unless you need precise control over hosts,
          paths, or limits.
        </p>
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        <TextArea
          label="Additional allowed hosts"
          value={form.additional_hosts}
          onChange={(value) => onUpdate("additional_hosts", value)}
          placeholder="assets.example.com (one per line)"
        />
        <TextArea
          label="Include paths"
          value={form.include_paths}
          onChange={(value) => onUpdate("include_paths", value)}
          placeholder="/docs/ (one per line)"
        />
        <TextArea
          label="Exclude paths"
          value={form.exclude_paths}
          onChange={(value) => onUpdate("exclude_paths", value)}
          placeholder="/archive/ (one per line)"
        />
        <div className="space-y-2">
          <Label htmlFor="change-detection">Change detection</Label>
          <Select
            value={form.change_detection}
            onValueChange={(value) =>
              onUpdate(
                "change_detection",
                value as UrlSourceForm["change_detection"],
              )
            }
          >
            <SelectTrigger id="change-detection">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="normalized_content_hash">
                Normalized content hash
              </SelectItem>
              <SelectItem value="always_reingest">Always re-ingest</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            {form.change_detection === "always_reingest"
              ? "Re-ingest every returned page, even if its content has not changed."
              : "Re-ingest only when normalized page content changes."}
          </p>
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
                pageScope && (key === "max_pages" || key === "max_depth")
              }
              value={
                pageScope && key === "max_pages"
                  ? 1
                  : pageScope && key === "max_depth"
                    ? 0
                    : form[key]
              }
              onChange={(event) => onUpdate(key, Number(event.target.value))}
            />
          </div>
        ))}
      </div>
      <div className="flex gap-3 border border-green-500/40 bg-green-500/10 p-4 text-sm">
        <Info className="size-5 shrink-0 text-green-600" />
        <p>
          <strong>Always-on safety</strong>
          <br />
          OpenRAG identifies itself, honors robots.txt, restricts redirects and
          approved hosts, blocks private/internal destinations, limits crawl
          size and time, and runs asynchronously within OpenRAG&apos;s task
          system. These controls cannot be disabled.
        </p>
      </div>
    </div>
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
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}
