"use client";

import {
  Check,
  ChevronsUpDown,
  Circle,
  Clock,
  FileIcon,
  Loader2,
  X,
} from "lucide-react";
import {
  type ReactNode,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  type Task,
  type TaskFileEntry,
  useGetTasksQuery,
} from "@/app/api/queries/useGetTasksQuery";
import {
  useDoclingPreviewQuery,
  useIndexProofQuery,
} from "@/app/api/queries/useIngestPreviewQuery";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useTask } from "@/contexts/task-context";
import {
  chunkPageToDoclingRef,
  inferChunkPageNumbering,
} from "@/lib/ingest-preview";
import { cn } from "@/lib/utils";

type DoclingImgElement = HTMLElement & {
  src?: Record<string, unknown> | string;
  items?: string | unknown[];
  trim?: string;
  itemStyle?: (page: unknown, item: unknown) => string;
};

const LAYOUT_BOX_STYLE = () =>
  "stroke: rgb(37, 99, 235); stroke-width: 2px; fill: rgba(37, 99, 235, 0.12); fill-opacity: 1;";

const PREVIEW_FRAME_CLASS =
  "max-h-[420px] overflow-auto rounded-md bg-background";

let doclingComponentsLoaded: Promise<void> | null = null;

function loadDoclingComponents(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.resolve();
  }
  if (!doclingComponentsLoaded) {
    doclingComponentsLoaded = import("@docling/docling-components").then(
      () => undefined,
    );
  }
  return doclingComponentsLoaded;
}

function DoclingParseViewer({
  doclingDocument,
  highlightItems,
}: {
  doclingDocument: Record<string, unknown>;
  highlightItems?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<DoclingImgElement | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void loadDoclingComponents().then(() => {
      if (!cancelled) {
        setReady(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!ready || !containerRef.current) {
      return;
    }

    const container = containerRef.current;
    if (!viewerRef.current || !container.contains(viewerRef.current)) {
      container.replaceChildren();
      const viewer = document.createElement("docling-img") as DoclingImgElement;
      viewer.setAttribute("pagenumbers", "");
      viewer.trim = "";
      viewer.itemStyle = LAYOUT_BOX_STYLE;
      container.appendChild(viewer);
      viewerRef.current = viewer;
    }

    const viewer = viewerRef.current;
    viewer.itemStyle = LAYOUT_BOX_STYLE;
    viewer.src = doclingDocument;
    if (highlightItems) {
      viewer.items = highlightItems;
    } else {
      viewer.items = undefined;
      viewer.removeAttribute("items");
    }
  }, [ready, doclingDocument, highlightItems]);

  return <div ref={containerRef} data-testid="docling-parse-viewer" />;
}

/**
 * Whether the Docling JSON embeds full-page renderings. Only PDFs and image
 * inputs produce these; office formats (docx/pptx/xlsx/…) parse to structured
 * items without page rasters, so `docling-img` would render blank for them.
 */
function doclingHasPageImages(document: Record<string, unknown>): boolean {
  const pages = (document as { pages?: unknown }).pages;
  if (!pages) {
    return false;
  }
  const pageList = Array.isArray(pages) ? pages : Object.values(pages);
  return pageList.some((page) => {
    const image = (page as { image?: unknown } | null)?.image;
    if (!image) {
      return false;
    }
    if (typeof image === "string") {
      return image.length > 0;
    }
    const { uri, data } = image as { uri?: unknown; data?: unknown };
    return Boolean(uri) || Boolean(data);
  });
}

type DoclingTextItem = {
  text?: string;
  label?: string;
  level?: number;
};

type DoclingTableCell = { text?: string };

type DoclingTableItem = {
  data?: { grid?: DoclingTableCell[][] };
};

type DoclingPictureItem = {
  image?: { uri?: string };
  captions?: unknown[];
};

type DoclingRef = { $ref?: string; cref?: string };

type BlockStyle = { name: string; border: string; chip: string };

// Type → bounding-box treatment. This is the non-paged analog of the docling-img
// layout boxes: since there's no page raster to overlay, we wrap each parsed
// region in its own colored, labeled box — same visual language, filled with the
// real content instead of drawn on a screenshot.
const LABEL_STYLES: Record<string, BlockStyle> = {
  title: {
    name: "Title",
    border: "border-indigo-500/70",
    chip: "bg-indigo-500 text-white",
  },
  section_header: {
    name: "Heading",
    border: "border-blue-500/70",
    chip: "bg-blue-500 text-white",
  },
  list_item: {
    name: "List",
    border: "border-amber-500/70",
    chip: "bg-amber-500 text-white",
  },
  caption: {
    name: "Caption",
    border: "border-slate-400/60",
    chip: "bg-slate-500 text-white",
  },
  page_header: {
    name: "Header",
    border: "border-slate-400/60",
    chip: "bg-slate-500 text-white",
  },
  page_footer: {
    name: "Footer",
    border: "border-slate-400/60",
    chip: "bg-slate-500 text-white",
  },
  footnote: {
    name: "Footnote",
    border: "border-slate-400/60",
    chip: "bg-slate-500 text-white",
  },
};

const DEFAULT_TEXT_STYLE: BlockStyle = {
  name: "Text",
  border: "border-sky-500/60",
  chip: "bg-sky-500 text-white",
};

const TABLE_STYLE: BlockStyle = {
  name: "Table",
  border: "border-emerald-500/70",
  chip: "bg-emerald-500 text-white",
};

const FIGURE_STYLE: BlockStyle = {
  name: "Figure",
  border: "border-purple-500/70",
  chip: "bg-purple-500 text-white",
};

function ParsedBlock({
  style,
  children,
}: {
  style: BlockStyle;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "relative rounded-md border-2 px-3 pt-4 pb-2",
        style.border,
      )}
    >
      <span
        className={cn(
          "absolute -top-2 left-2 rounded px-1 py-px text-xxs font-medium uppercase leading-none tracking-wide",
          style.chip,
        )}
      >
        {style.name}
      </span>
      {children}
    </div>
  );
}

function DoclingTextLine({ item }: { item: DoclingTextItem }) {
  const text = item.text?.trim();
  if (!text) {
    return null;
  }
  const label = item.label ?? "text";
  const style = LABEL_STYLES[label] ?? DEFAULT_TEXT_STYLE;
  const textClass =
    label === "title"
      ? "text-sm font-bold text-foreground"
      : label === "section_header"
        ? "text-sm font-semibold text-foreground"
        : label === "list_item"
          ? "pl-2 text-xs text-foreground"
          : "text-xs text-foreground";
  return (
    <ParsedBlock style={style}>
      <p className={textClass}>{label === "list_item" ? `• ${text}` : text}</p>
    </ParsedBlock>
  );
}

function DoclingTableBlock({ table }: { table: DoclingTableItem }) {
  const grid = table.data?.grid;
  if (!Array.isArray(grid) || grid.length === 0) {
    return null;
  }
  return (
    <ParsedBlock style={TABLE_STYLE}>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xxs">
          <tbody>
            {grid.map((row, rowIndex) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: parsed grid is static
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td
                    // biome-ignore lint/suspicious/noArrayIndexKey: parsed grid is static
                    key={cellIndex}
                    className="border border-border/40 px-2 py-1 align-top text-foreground"
                  >
                    {cell?.text ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ParsedBlock>
  );
}

function DoclingPictureBlock({ picture }: { picture: DoclingPictureItem }) {
  const uri = picture.image?.uri;
  if (!uri) {
    return (
      <ParsedBlock style={FIGURE_STYLE}>
        <p className="text-xxs text-muted-foreground">
          Figure detected (image not embedded).
        </p>
      </ParsedBlock>
    );
  }
  return (
    <ParsedBlock style={FIGURE_STYLE}>
      {/* biome-ignore lint/performance/noImgElement: data URI from parsed preview */}
      <img
        src={uri}
        alt="Parsed figure"
        className="max-h-48 rounded border border-border/40 bg-background object-contain"
      />
    </ParsedBlock>
  );
}

function refPath(ref: DoclingRef | undefined): string | undefined {
  return ref?.$ref ?? ref?.cref;
}

function resolveRef(
  document: Record<string, unknown>,
  path: string,
): Record<string, unknown> | null {
  if (!path.startsWith("#/")) {
    return null;
  }
  let node: unknown = document;
  for (const part of path.slice(2).split("/")) {
    if (node == null) {
      return null;
    }
    node = Array.isArray(node)
      ? node[Number(part)]
      : (node as Record<string, unknown>)[part];
  }
  return (node as Record<string, unknown>) ?? null;
}

type ParsedItem =
  | { kind: "text"; node: DoclingTextItem }
  | { kind: "table"; node: DoclingTableItem }
  | { kind: "picture"; node: DoclingPictureItem };

/**
 * Walks the DoclingDocument body in reading order, resolving refs to texts,
 * tables, and pictures (recursing through groups). Falls back to concatenating
 * the top-level arrays when no body ordering is present.
 */
function collectParsedItems(document: Record<string, unknown>): ParsedItem[] {
  const result: ParsedItem[] = [];
  const seen = new Set<string>();

  const walk = (children: unknown): void => {
    if (!Array.isArray(children)) {
      return;
    }
    for (const ref of children) {
      const path = refPath(ref as DoclingRef);
      if (!path || seen.has(path)) {
        continue;
      }
      seen.add(path);
      const node = resolveRef(document, path);
      if (!node) {
        continue;
      }
      if (path.startsWith("#/texts")) {
        result.push({ kind: "text", node });
      } else if (path.startsWith("#/tables")) {
        result.push({ kind: "table", node });
      } else if (path.startsWith("#/pictures")) {
        result.push({ kind: "picture", node });
      } else if (path.startsWith("#/groups")) {
        walk(node.children);
      }
    }
  };

  const body = document.body as { children?: unknown } | undefined;
  walk(body?.children);

  if (result.length === 0) {
    for (const node of (document.texts as DoclingTextItem[] | undefined) ??
      []) {
      result.push({ kind: "text", node });
    }
    for (const node of (document.tables as DoclingTableItem[] | undefined) ??
      []) {
      result.push({ kind: "table", node });
    }
    for (const node of (document.pictures as
      | DoclingPictureItem[]
      | undefined) ?? []) {
      result.push({ kind: "picture", node });
    }
  }
  return result;
}

/**
 * Renders the parsed structure for formats that have no page rasters (docx,
 * pptx, xlsx, html, csv, md, …). The Docling web components
 * (`docling-img`/`docling-table`) are page-based and render blank without page
 * images, so we render the structured items from the DoclingDocument directly,
 * color-coded by the structure Docling classified — a visual indication of the
 * parse standing in for the layout boxes we can only draw on paged formats.
 */
function DoclingTextPreview({
  doclingDocument,
}: {
  doclingDocument: Record<string, unknown>;
}) {
  const items = useMemo(
    () => collectParsedItems(doclingDocument),
    [doclingDocument],
  );

  if (items.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center px-4 text-center text-xxs text-muted-foreground">
        Parsing finished, but no extractable text or tables were found in this
        document.
      </div>
    );
  }

  return (
    <div
      className="space-y-3 rounded-md border border-border/40 bg-white p-4 shadow-sm dark:bg-slate-900"
      data-testid="docling-text-preview"
    >
      {items.map((item, index) => {
        if (item.kind === "table") {
          return (
            // biome-ignore lint/suspicious/noArrayIndexKey: parsed items are static
            <DoclingTableBlock key={`item-${index}`} table={item.node} />
          );
        }
        if (item.kind === "picture") {
          return (
            // biome-ignore lint/suspicious/noArrayIndexKey: parsed items are static
            <DoclingPictureBlock key={`item-${index}`} picture={item.node} />
          );
        }
        return (
          // biome-ignore lint/suspicious/noArrayIndexKey: parsed items are static
          <DoclingTextLine key={`item-${index}`} item={item.node} />
        );
      })}
    </div>
  );
}

const TEXT_LIKE_EXTENSIONS = new Set([
  "txt",
  "md",
  "markdown",
  "csv",
  "tsv",
  "json",
  "jsonl",
  "ndjson",
  "yaml",
  "yml",
  "xml",
  "html",
  "htm",
  "log",
  "rst",
  "ini",
  "toml",
]);

function isTextLike(file: File): boolean {
  if (file.type.startsWith("text/")) {
    return true;
  }
  if (
    file.type === "application/json" ||
    file.type === "application/xml" ||
    file.type === "application/xhtml+xml"
  ) {
    return true;
  }
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  return TEXT_LIKE_EXTENSIONS.has(ext);
}

function LocalUploadPreview({ file }: { file: File }) {
  const textLike = isTextLike(file);

  const objectUrl = useMemo(() => {
    if (file.type === "application/pdf" || file.type.startsWith("image/")) {
      return URL.createObjectURL(file);
    }
    return null;
  }, [file]);

  const [textPreview, setTextPreview] = useState<string | null>(null);

  useEffect(() => {
    if (!textLike) {
      return;
    }
    let cancelled = false;
    void file.text().then((text) => {
      if (!cancelled) {
        setTextPreview(text.slice(0, 8000));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [file, textLike]);

  useEffect(() => {
    return () => {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [objectUrl]);

  if (file.type === "application/pdf" && objectUrl) {
    // Render through <object> with an explicit type so the blob bytes are handed
    // to the browser's PDF viewer instead of being interpreted as a document. A
    // blob: URL in an <iframe src> would render HTML/SVG payloads in our origin
    // (DOM-XSS, since file.type is attacker-controlled); pinning
    // type="application/pdf" forces PDF handling and also fixes Safari, which
    // won't display PDFs inside an <iframe>.
    return (
      <object
        data={objectUrl}
        type="application/pdf"
        aria-label={file.name}
        className="h-[420px] w-full rounded-md border border-border/40 bg-background"
        data-testid="local-upload-preview-pdf"
      >
        <div className="flex h-56 items-center justify-center px-4 text-center text-xxs text-muted-foreground">
          Preview unavailable — the document is still being parsed.
        </div>
      </object>
    );
  }

  if (file.type.startsWith("image/") && objectUrl) {
    return (
      <img
        src={objectUrl}
        alt={file.name}
        className="max-h-[420px] w-full rounded-md border border-border/40 bg-background object-contain"
        data-testid="local-upload-preview-image"
      />
    );
  }

  if (textLike) {
    if (textPreview == null) {
      return (
        <div className="flex h-56 items-center justify-center text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading preview…
        </div>
      );
    }
    return (
      <pre
        className="max-h-[420px] overflow-auto rounded-md border border-border/40 bg-background p-3 text-xxs whitespace-pre-wrap"
        data-testid="local-upload-preview-text"
      >
        {textPreview}
        {textPreview.length >= 8000 ? "\n…" : ""}
      </pre>
    );
  }

  return (
    <div
      className="flex h-56 flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border/60 bg-background px-4 text-center text-muted-foreground"
      data-testid="local-upload-preview-fallback"
    >
      <FileIcon className="h-8 w-8 opacity-60" />
      <p className="text-sm font-medium text-foreground">{file.name}</p>
      <p className="text-xxs">Layout boxes appear once parsing finishes.</p>
    </div>
  );
}

function ProofLine({
  done,
  label,
  failed = false,
  idle = false,
}: {
  done: boolean;
  label: string;
  failed?: boolean;
  idle?: boolean;
}) {
  return (
    <li className="flex items-center gap-2">
      {failed ? (
        <X className="h-4 w-4 text-destructive shrink-0" />
      ) : done ? (
        <Check className="h-4 w-4 text-green-600 shrink-0" />
      ) : idle ? (
        <Circle className="h-4 w-4 text-muted-foreground/40 shrink-0" />
      ) : (
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground shrink-0" />
      )}
      <span
        className={cn(
          failed
            ? "text-destructive"
            : done
              ? "text-foreground"
              : "text-muted-foreground",
        )}
      >
        {label}
      </span>
    </li>
  );
}

interface IngestPreviewPanelProps {
  taskId?: string | null;
  previewFile?: File | null;
  /** Specific file (file_path key from /tasks/enhanced) to preview. */
  filePath?: string | null;
  /** Pre-resolved task file entry; when omitted it is derived from the task. */
  fileEntry?: TaskFileEntry;
  /** Invoked when the user opts to inspect the failure in the task panel. */
  onViewError?: (taskId: string) => void;
}

function isFileEntryFailed(entry?: TaskFileEntry): boolean {
  return entry?.status === "failed" || entry?.status === "error";
}

export function IngestPreviewPanel({
  taskId,
  previewFile,
  filePath = null,
  fileEntry,
  onViewError,
}: IngestPreviewPanelProps) {
  const activeTaskId = taskId || null;
  const { openTaskDialog } = useTask();

  // Failure + phase come from the shared enhanced task backend (/tasks/enhanced),
  // the same source the task panel uses. The preview-only endpoints below stay
  // scoped to the layout document and indexed-chunk proof.
  const { data: tasks } = useGetTasksQuery({
    enabled: Boolean(activeTaskId) && !fileEntry,
  });
  const task = activeTaskId
    ? tasks?.find((t) => t.task_id === activeTaskId)
    : undefined;
  const fileEntries = task?.files ? Object.values(task.files) : [];

  // Scope failure to the selected file when a filePath is given; otherwise fall
  // back to any failed file in the task (single-file / back-compat).
  const resolvedEntry =
    fileEntry ??
    (filePath ? task?.files?.[filePath] : undefined) ??
    fileEntries.find(isFileEntryFailed);
  const taskFailed = task?.status === "failed" || task?.status === "error";
  const ingestFailed = filePath
    ? isFileEntryFailed(resolvedEntry)
    : isFileEntryFailed(resolvedEntry) || taskFailed;
  const failureMessage =
    resolvedEntry?.user_facing_message ||
    resolvedEntry?.error ||
    task?.error ||
    "Ingestion failed. Please try again.";
  const failurePhase = resolvedEntry?.failure_phase;
  const filePhase = resolvedEntry?.phase;

  const { data: parsePreview, isLoading: parseLoading } =
    useDoclingPreviewQuery(
      activeTaskId,
      Boolean(activeTaskId) && !ingestFailed,
      filePath,
    );
  const { data: indexProof } = useIndexProofQuery(
    activeTaskId,
    Boolean(activeTaskId) && !ingestFailed,
    filePath,
  );
  const [highlightItems, setHighlightItems] = useState<string | undefined>();
  const [prevTaskId, setPrevTaskId] = useState(activeTaskId);
  if (activeTaskId !== prevTaskId) {
    setPrevTaskId(activeTaskId);
    setHighlightItems(undefined);
  }

  // The layout cache is ephemeral (~30 min TTL). If Docling already finished
  // (phase past docling) but no document comes back, the live preview expired.
  const doclingFinished = filePhase === "langflow" || filePhase === "complete";
  const previewExpired =
    !ingestFailed &&
    !parsePreview?.document &&
    !parseLoading &&
    doclingFinished;

  const handleViewError = () => {
    if (!activeTaskId) {
      return;
    }
    if (onViewError) {
      onViewError(activeTaskId);
    } else {
      openTaskDialog(activeTaskId);
    }
  };

  const pageNumbering = useMemo(
    () => inferChunkPageNumbering(indexProof?.chunks ?? []),
    [indexProof?.chunks],
  );

  const layoutReady = Boolean(parsePreview?.document);
  const hasPageImages = useMemo(
    () =>
      parsePreview?.document
        ? doclingHasPageImages(parsePreview.document)
        : false,
    [parsePreview?.document],
  );
  const layoutLabel = layoutReady
    ? "Layout parsed"
    : previewFile
      ? "Reading layout & structure"
      : "Layout parsed";

  const chunksDone = (indexProof?.chunk_count ?? 0) > 0;
  const embeddingsDone = Boolean(indexProof?.embedding_dimensions);
  const storedDone = Boolean(indexProof?.ready);

  const steps = [
    { id: "layout", done: layoutReady, label: layoutLabel },
    {
      id: "chunks",
      done: chunksDone,
      label: chunksDone
        ? `${indexProof?.chunk_count} chunks created`
        : "Creating chunks",
    },
    {
      id: "embeddings",
      done: embeddingsDone,
      label: embeddingsDone
        ? `Embeddings (${indexProof?.embedding_dimensions}-d · ${indexProof?.embedding_model ?? "model"})`
        : "Generating embeddings",
    },
    { id: "stored", done: storedDone, label: "Stored in OpenSearch" },
  ];

  // Map the classified failure phase to a step so the error lands on the right
  // line; fall back to the first step that hasn't completed.
  const failedStepIndex = (() => {
    if (!ingestFailed) {
      return -1;
    }
    const byPhase: Record<string, number> = {
      parsing: 0,
      file_validation: 0,
      chunking: 1,
      embedding: 2,
      indexing: 3,
    };
    if (failurePhase && failurePhase in byPhase) {
      return byPhase[failurePhase];
    }
    const firstNotDone = steps.findIndex((s) => !s.done);
    return firstNotDone === -1 ? steps.length - 1 : firstNotDone;
  })();

  return (
    <div
      className="grid gap-4 lg:grid-cols-2 mt-4"
      data-testid="ingest-preview-panel"
    >
      <div className="rounded-lg border border-border/60 bg-muted/30 p-3 min-h-[280px]">
        <div className="mb-2 flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Parsed layout</h3>
          {parsePreview?.stats && (
            <Badge variant="secondary" className="text-xxs">
              {parsePreview.stats.text_count} text ·{" "}
              {parsePreview.stats.table_count} tables ·{" "}
              {parsePreview.stats.picture_count} figures
            </Badge>
          )}
        </div>

        {layoutReady ? (
          hasPageImages ? (
            <div className={PREVIEW_FRAME_CLASS}>
              <p className="mb-2 text-xxs text-muted-foreground">
                Blue boxes mark parsed text, tables, and figures.
                {indexProof?.chunks?.length
                  ? " Click a chunk to focus a page."
                  : null}
              </p>
              <DoclingParseViewer
                doclingDocument={parsePreview!.document}
                highlightItems={highlightItems}
              />
            </div>
          ) : (
            // Office/non-paged formats (docx, pptx, xlsx, html, csv, …) have no
            // page raster to overlay boxes on, so we render each detected region
            // as its own colored, labeled box — the same visual language as the
            // docling-img boxes, filled with the parsed content.
            <div className={PREVIEW_FRAME_CLASS}>
              <p className="mb-2 text-xxs text-muted-foreground">
                No page image for this format — each region Docling detected is
                boxed and labeled by type.
              </p>
              <DoclingTextPreview doclingDocument={parsePreview!.document} />
            </div>
          )
        ) : ingestFailed ? (
          <div
            className="flex h-56 flex-col items-center justify-center gap-2 px-4 text-center text-muted-foreground"
            data-testid="ingest-preview-failed"
          >
            <X className="h-8 w-8 text-destructive opacity-80" />
            <p className="text-sm font-medium text-destructive">
              Parsing failed
            </p>
            <p className="text-xxs">{failureMessage}</p>
          </div>
        ) : previewFile ? (
          // We still hold the original file from this session. Render it
          // (createObjectURL) while this specific file's Docling parse is still
          // in flight — each file is its own Docling task, so a freshly selected
          // file may not be parsed yet. Prefer this over the "expired" state so
          // the pane is never blank for files the user just uploaded.
          <div className={PREVIEW_FRAME_CLASS}>
            <p className="mb-2 text-xxs text-muted-foreground">
              Original file — layout boxes appear when parsing finishes.
            </p>
            <LocalUploadPreview file={previewFile} />
          </div>
        ) : previewExpired ? (
          <div
            className="flex h-56 flex-col items-center justify-center gap-2 px-4 text-center text-muted-foreground"
            data-testid="ingest-preview-expired"
          >
            <Clock className="h-8 w-8 opacity-60" />
            <p className="text-sm font-medium text-foreground">
              Live preview ended
            </p>
            <p className="text-xxs">
              This document is still indexed and searchable.
            </p>
          </div>
        ) : (
          // No local file and Docling hasn't returned a layout yet. The query
          // keeps polling (1.5s) until the document is ready; show a spinner
          // instead of going blank.
          <div className="flex h-56 items-center justify-center text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Reading document structure…
          </div>
        )}
      </div>

      <div className="rounded-lg border border-border/60 bg-muted/30 p-3 min-h-[280px]">
        <h3 className="text-sm font-semibold mb-3">Search index</h3>
        <ul className="space-y-2 mb-4 text-sm">
          {steps.map((step, i) => {
            const isFailed = ingestFailed && i === failedStepIndex;
            const isIdle = ingestFailed && i > failedStepIndex && !step.done;
            return (
              <ProofLine
                key={step.id}
                done={step.done && !isFailed}
                failed={isFailed}
                idle={isIdle}
                label={isFailed ? failureMessage : step.label}
              />
            );
          })}
        </ul>

        {ingestFailed && activeTaskId && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mb-4 w-full"
            data-testid="ingest-preview-view-error"
            onClick={handleViewError}
          >
            View error details &amp; retry
          </Button>
        )}

        {indexProof?.chunks && indexProof.chunks.length > 0 && (
          <div className="space-y-2 max-h-48 overflow-auto">
            {indexProof.chunks.slice(0, 6).map((chunk) => (
              <button
                key={chunk.chunk_id}
                type="button"
                className={cn(
                  "w-full rounded-md border border-border/40 bg-background/80 px-2 py-1.5 text-left text-xxs text-muted-foreground transition-colors hover:border-primary/40",
                  chunk.page != null &&
                    highlightItems ===
                      chunkPageToDoclingRef(chunk.page, pageNumbering) &&
                    "border-primary/60 ring-1 ring-primary/30",
                )}
                onClick={() => {
                  if (chunk.page == null) {
                    setHighlightItems(undefined);
                    return;
                  }
                  const pageRef = chunkPageToDoclingRef(
                    chunk.page,
                    pageNumbering,
                  );
                  setHighlightItems((current) =>
                    current === pageRef ? undefined : pageRef,
                  );
                }}
              >
                <div className="font-medium text-foreground mb-0.5">
                  {chunk.chunk_id}
                  {chunk.page != null ? ` · page ${chunk.page}` : ""} ·{" "}
                  {chunk.char_count} chars
                </div>
                <p className="line-clamp-2">{chunk.text_preview}</p>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

interface CarouselFile {
  taskId: string | null;
  filePath: string | null;
  entry?: TaskFileEntry;
  filename: string;
}

/**
 * Flatten the files of every task in {@link taskIds} into a single ordered list.
 * Folder uploads are split into multiple batch tasks, so the carousel spans
 * them to present one continuous set of files.
 */
function carouselFilesFromTasks(
  tasks: Task[] | undefined,
  taskIds: string[],
): CarouselFile[] {
  if (!tasks || taskIds.length === 0) {
    return [];
  }
  const idSet = new Set(taskIds);
  const tasksById = new Map(tasks.map((task) => [task.task_id, task]));
  const files: CarouselFile[] = [];
  for (const id of taskIds) {
    const task = tasksById.get(id);
    if (!task?.files || !idSet.has(task.task_id)) {
      continue;
    }
    for (const [filePath, entry] of Object.entries(task.files)) {
      files.push({
        taskId: task.task_id,
        filePath,
        entry,
        filename: entry.filename ?? filePath.split("/").pop() ?? filePath,
      });
    }
  }
  return files;
}

/** A file is viewable once Docling has finished (phase past docling). */
function isPreviewReady(entry?: TaskFileEntry): boolean {
  return entry?.phase === "langflow" || entry?.phase === "complete";
}

/**
 * Searchable file picker for the preview carousel. Scales to large batches —
 * type to filter by filename, each item flagged ready vs still processing.
 */
function PreviewFileSelector({
  files,
  activeIndex,
  onSelect,
}: {
  files: CarouselFile[];
  activeIndex: number;
  onSelect: (index: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const listboxId = useId();
  const active = files[activeIndex];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          role="combobox"
          aria-expanded={open}
          aria-controls={listboxId}
          className="min-w-0 flex-1 justify-between gap-2"
          data-testid="ingest-preview-file-selector"
        >
          <span className="truncate" title={active?.filename}>
            {active?.filename ?? "Select file"}
          </span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[var(--radix-popover-trigger-width)] p-0"
        align="start"
      >
        <Command>
          <CommandInput placeholder="Search files…" />
          <CommandList id={listboxId}>
            <CommandEmpty>No files found.</CommandEmpty>
            <CommandGroup>
              {files.map((file, index) => {
                const ready = isPreviewReady(file.entry);
                return (
                  <CommandItem
                    key={file.filePath ?? `local-${index}`}
                    value={`idx-${index}`}
                    keywords={[file.filename]}
                    onSelect={() => {
                      onSelect(index);
                      setOpen(false);
                    }}
                    className="gap-2"
                  >
                    <Check
                      className={cn(
                        "h-4 w-4 shrink-0",
                        index === activeIndex ? "opacity-100" : "opacity-0",
                      )}
                    />
                    <span
                      className="min-w-0 flex-1 truncate"
                      title={file.filename}
                    >
                      {file.filename}
                    </span>
                    <span
                      className={cn(
                        "shrink-0 text-xxs",
                        ready
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-muted-foreground",
                      )}
                    >
                      {ready ? "ready" : "processing"}
                    </span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

interface IngestPreviewCarouselProps {
  /** One or more preview-mode task ids (folder uploads produce several). */
  taskIds: string[];
  previewFiles?: File[];
  onViewError?: (taskId: string) => void;
}

/**
 * Steps through every file across one or more preview-mode ingest tasks,
 * rendering the per-file Docling layout + index proof. Before the tasks are
 * visible it falls back to the locally selected files so the user sees their
 * originals immediately.
 */
export function IngestPreviewCarousel({
  taskIds,
  previewFiles,
  onViewError,
}: IngestPreviewCarouselProps) {
  const { data: tasks } = useGetTasksQuery({
    enabled: taskIds.length > 0,
  });

  const files = useMemo<CarouselFile[]>(() => {
    const fromTasks = carouselFilesFromTasks(tasks, taskIds);
    if (fromTasks.length > 0) {
      return fromTasks;
    }
    return (previewFiles ?? []).map((file) => ({
      taskId: null,
      filePath: null,
      filename: file.name,
    }));
  }, [tasks, taskIds, previewFiles]);

  // Track the selection by filename rather than index. The files list is
  // rebuilt on every task poll and as folder batches arrive, so an index would
  // silently point at a different file (the "jumping carousel" bug).
  const [selectedFilename, setSelectedFilename] = useState<string | null>(null);

  const activeIndex = useMemo(() => {
    if (files.length === 0) {
      return 0;
    }
    if (selectedFilename) {
      const found = files.findIndex((f) => f.filename === selectedFilename);
      if (found >= 0) {
        return found;
      }
    }
    return 0;
  }, [files, selectedFilename]);

  const selectIndex = (index: number) => {
    const file = files[index];
    if (file) {
      setSelectedFilename(file.filename);
    }
  };

  const active = files[activeIndex];
  const localFile =
    (previewFiles ?? []).find((file) => file.name === active?.filename) ?? null;
  const canNavigate = files.length > 1;
  const plural = files.length > 1;

  return (
    <div data-testid="ingest-preview-carousel">
      {canNavigate && (
        <div className="mb-2 flex items-center gap-2">
          <PreviewFileSelector
            files={files}
            activeIndex={activeIndex}
            onSelect={selectIndex}
          />
          <span className="shrink-0 text-xxs text-muted-foreground tabular-nums">
            {activeIndex + 1}/{files.length}
          </span>
        </div>
      )}

      <IngestPreviewPanel
        key={
          active?.filePath
            ? `${active.taskId}:${active.filePath}`
            : `local:${active?.filename ?? activeIndex}`
        }
        taskId={active?.taskId ?? taskIds[0] ?? null}
        filePath={active?.filePath ?? null}
        fileEntry={active?.entry}
        previewFile={localFile}
        onViewError={onViewError}
      />

      <p className="mt-3 text-xxs text-muted-foreground">
        Live parse preview — available only while your{" "}
        {plural ? "documents are" : "document is"} processing. Your{" "}
        {plural ? "files stay" : "file stays"} indexed and searchable afterward.
      </p>
    </div>
  );
}

interface IngestPreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Single task id (single/multi file upload). */
  taskId?: string | null;
  /** Multiple task ids (folder uploads batched into several tasks). */
  taskIds?: string[];
  filename?: string;
  previewFile?: File | null;
  previewFiles?: File[];
}

export function IngestPreviewDialog({
  open,
  onOpenChange,
  taskId,
  taskIds,
  filename,
  previewFile,
  previewFiles,
}: IngestPreviewDialogProps) {
  const { openTaskDialog } = useTask();
  const files = previewFiles ?? (previewFile ? [previewFile] : []);
  const ids = taskIds ?? (taskId ? [taskId] : []);

  if (!open || (ids.length === 0 && files.length === 0)) {
    return null;
  }

  const handleViewError = (id: string) => {
    onOpenChange(false);
    openTaskDialog(id);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-5xl max-h-[90vh] overflow-y-auto"
        data-testid="ingest-preview-dialog"
      >
        <DialogHeader>
          <DialogTitle>Live ingest preview</DialogTitle>
          <DialogDescription>
            {filename
              ? `How "${filename}" is parsed and indexed.`
              : "Live parse layout and search index progress."}
          </DialogDescription>
        </DialogHeader>
        <IngestPreviewCarousel
          taskIds={ids}
          previewFiles={files}
          onViewError={handleViewError}
        />
      </DialogContent>
    </Dialog>
  );
}
