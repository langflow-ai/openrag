import { KnowledgeUrlIcon } from "@/components/knowledge-url-icon";
import type { WebsiteSource } from "./types";

const lastSyncFormatter = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function formatLastSync(value?: string | null) {
  if (!value) return "Last synced —";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Last synced —";
  return `Last synced ${lastSyncFormatter.format(date)}`;
}

export function WebsitePagesHeader({
  source,
  pageCount,
  onNavigateBack,
}: {
  source: WebsiteSource;
  pageCount: number;
  onNavigateBack(): void;
}) {
  return (
    <header className="mb-6">
      <div className="mb-5 flex items-center gap-2 text-sm">
        <button
          type="button"
          className="text-primary hover:underline"
          onClick={onNavigateBack}
        >
          Project knowledge
        </button>
        <span className="text-muted-foreground">/</span>
        <span className="text-foreground">{source.name}</span>
      </div>
      <div className="flex min-w-0 items-center gap-2">
        <KnowledgeUrlIcon className="size-5 text-foreground" />
        <h1 className="min-w-0 truncate text-3xl font-normal tracking-tight">
          {source.name}
        </h1>
      </div>
      <div className="ml-7 mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <a
          href={source.starting_url}
          target="_blank"
          rel="noopener noreferrer"
          className="max-w-full truncate text-primary hover:underline"
        >
          {source.starting_url}
        </a>
        <span aria-hidden="true" className="text-muted-foreground">
          ·
        </span>
        <span className="text-muted-foreground">
          {source.web_child_count ?? pageCount} pages indexed
        </span>
        <span aria-hidden="true" className="text-muted-foreground">
          ·
        </span>
        <span className="text-muted-foreground">
          {formatLastSync(source.last_successful_sync_at)}
        </span>
      </div>
    </header>
  );
}
