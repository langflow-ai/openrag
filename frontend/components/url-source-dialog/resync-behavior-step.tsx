import { Label } from "@/components/ui/label";
import { Choice } from "./choice";
import type { UpdateUrlSourceForm, UrlSourceForm } from "./form";

export function ResyncBehaviorStep({
  form,
  onUpdate,
}: {
  form: UrlSourceForm;
  onUpdate: UpdateUrlSourceForm;
}) {
  return (
    <div className="space-y-8 px-3 py-6">
      <div>
        <h3 className="text-lg font-semibold">How should re-syncs work?</h3>
        <p className="text-sm text-muted-foreground">
          Choose what happens when OpenRAG revisits this website.
        </p>
      </div>
      <div className="space-y-3">
        <div className="space-y-1.5">
          <Label>RE-SYNC BEHAVIOR</Label>
          <p className="text-sm text-muted-foreground">
            When a scheduled or manual re-crawl runs, which pages get ingested?
          </p>
        </div>
        <div className="flex flex-col sm:flex-row">
          <Choice
            selected={form.resync_behavior === "full"}
            onClick={() => onUpdate("resync_behavior", "full")}
            title="Full crawl; ingest returned pages"
            detail="Repeat the saved crawl scope and reconcile returned pages."
          />
          <Choice
            selected={form.resync_behavior === "root"}
            onClick={() => onUpdate("resync_behavior", "root")}
            title="Ingest only root page"
            detail="Update the starting page and leave existing children unchanged."
          />
        </div>
      </div>
      <div className="space-y-3">
        <div className="space-y-1.5">
          <Label>REMOVED PAGES</Label>
          <p className="text-sm text-muted-foreground">
            What should happen to pages that disappear from the site?
          </p>
        </div>
        <div className="flex flex-col sm:flex-row">
          <Choice
            selected={form.removed_page_behavior === "retain"}
            onClick={() => onUpdate("removed_page_behavior", "retain")}
            title="Retain in corpus"
            detail="Keep the last indexed copy when a page disappears."
          />
          <Choice
            selected={form.removed_page_behavior === "delete"}
            onClick={() => onUpdate("removed_page_behavior", "delete")}
            title="Delete"
            detail="Delete pages absent from a complete, successful full crawl."
          />
        </div>
        <p className="text-sm text-muted-foreground">
          Incomplete or capped crawls never delete missing pages.
        </p>
      </div>
    </div>
  );
}
