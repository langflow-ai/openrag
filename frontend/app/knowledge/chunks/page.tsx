"use client";

import { ArrowLeft, Loader2, Search } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useFileScopedChunksQuery } from "@/app/api/queries/useFileScopedChunksQuery";
import { FileChunksPanel } from "@/components/file-chunks-panel";
import { ProtectedRoute } from "@/components/protected-route";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { formatFileSize, getFileTypeLabel } from "@/lib/file-format";

/** How long to wait after the user stops typing before firing a highlight fetch. */
const HIGHLIGHT_DEBOUNCE_MS = 400;

function ChunksPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const filename = searchParams.get("filename");

  // initialQuery comes from ?q= (set when navigating from the knowledge page).
  const initialQuery = searchParams.get("q") ?? "";

  // localQuery drives both the local chunk filter and (debounced) the highlight
  // fetch. Initialised from the URL so arriving with ?q=fantasy football
  // pre-fills the search box and shows highlights immediately.
  const [localQuery, setLocalQuery] = useState(initialQuery);

  // searchQuery is the debounced value sent to the highlight API. We keep it
  // separate so typing doesn't hammer the backend on every keystroke.
  const [searchQuery, setSearchQuery] = useState(initialQuery);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleQueryChange = useCallback(
    (value: string) => {
      setLocalQuery(value);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        setSearchQuery(value);
        // Keep the URL in sync so the user can share/refresh the page.
        const params = new URLSearchParams({ filename: filename ?? "" });
        if (value.trim() && value.trim() !== "*") params.set("q", value.trim());
        router.replace(`/knowledge/chunks?${params.toString()}`, {
          scroll: false,
        });
      }, HIGHLIGHT_DEBOUNCE_MS);
    },
    [filename, router],
  );

  // Clean up any pending debounce on unmount.
  useEffect(
    () => () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    },
    [],
  );

  const { file: fileData } = useFileScopedChunksQuery(
    filename,
    searchQuery || undefined,
  );

  if (!filename) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <Search className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
          <p className="text-lg text-muted-foreground">No file specified</p>
          <p className="text-sm text-muted-foreground/70 mt-2">
            Please select a file from the knowledge page
          </p>
        </div>
      </div>
    );
  }

  const chunks = fileData?.chunks ?? [];
  const chunkCount = chunks.length;
  const averageChunkLength =
    chunkCount === 0
      ? 0
      : chunks.reduce((acc, chunk) => acc + chunk.text.length, 0) / chunkCount;

  const hasAccessControl =
    Boolean(fileData?.owner) ||
    (fileData?.allowed_users?.length ?? 0) > 0 ||
    (fileData?.allowed_groups?.length ?? 0) > 0;

  return (
    <div className="flex flex-col h-full">
      <div className="flex flex-col mb-6">
        <div className="flex items-center gap-3 mb-6">
          <Button
            variant="ghost"
            onClick={() => router.push("/knowledge")}
            size="sm"
            className="max-w-8 max-h-8 -m-2"
          >
            <ArrowLeft size={24} />
          </Button>
          <h1 className="text-lg font-semibold">
            {filename.replace(/\.[^/.]+$/, "")}
          </h1>
        </div>
      </div>

      <div className="grid gap-6 grid-cols-1 lg:grid-cols-[3fr_1fr]">
        <div className="row-start-2 lg:row-start-1">
          <FileChunksPanel
            filename={filename}
            searchQuery={searchQuery || undefined}
            filterQuery={localQuery}
            onFilterQueryChange={handleQueryChange}
          />
        </div>

        {chunkCount > 0 && (
          <div className="min-w-[200px]">
            {/* Heading row — on narrow view the owner sits flush right */}
            <div className="flex items-center mb-4">
              <h2 className="text-xl font-semibold">Document Details</h2>
              {fileData?.owner && (
                <span className="lg:hidden flex items-center gap-1.5 text-sm text-muted-foreground ps-3">
                  Owned by:{" "}
                  <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900">
                    <span className="text-xs font-medium text-amber-800 dark:text-amber-200">
                      {String(fileData.owner).charAt(0).toUpperCase()}
                    </span>
                  </span>
                  <span className="text-foreground">
                    {fileData.owner_name ||
                      fileData.owner_email ||
                      fileData.owner}
                  </span>
                </span>
              )}
            </div>

            {/*
              Narrow (< lg): unified 2-col grid, cells flush together (no gap-y).
              Wide (≥ lg): single-column stacked label/value list.
            */}
            <dl className="grid grid-cols-2 gap-x-4 gap-y-0 lg:grid-cols-1">
              <div className="pb-2.5 lg:grid lg:grid-cols-3 lg:gap-4 lg:pb-0 lg:mb-2.5">
                <dt className="text-sm/6 text-muted-foreground">
                  Total chunks
                </dt>
                <dd className="text-sm/6 text-foreground lg:col-span-2">
                  {chunkCount}
                </dd>
              </div>
              <div className="pb-2.5 lg:grid lg:grid-cols-3 lg:gap-4 lg:pb-0 lg:mb-2.5">
                <dt className="text-sm/6 text-muted-foreground">Avg length</dt>
                <dd className="text-sm/6 text-foreground lg:col-span-2">
                  {averageChunkLength.toFixed(0)} chars
                </dd>
              </div>
              <div className="pb-2.5 lg:grid lg:grid-cols-3 lg:gap-4 lg:pb-0 lg:mb-2.5">
                <dt className="text-sm/6 text-muted-foreground">Type</dt>
                <dd className="text-sm/6 text-foreground lg:col-span-2">
                  {fileData ? getFileTypeLabel(fileData.mimetype) : "Unknown"}
                </dd>
              </div>
              <div className="pb-2.5 lg:grid lg:grid-cols-3 lg:gap-4 lg:pb-0 lg:mb-2.5">
                <dt className="text-sm/6 text-muted-foreground">Size</dt>
                <dd className="text-sm/6 text-foreground lg:col-span-2">
                  {fileData?.size ? formatFileSize(fileData.size) : "Unknown"}
                </dd>
              </div>
              {fileData?.embedding_model && (
                <div className="pb-2.5 lg:grid lg:grid-cols-3 lg:gap-4 lg:pb-0 lg:mb-2.5">
                  <dt className="text-sm/6 text-muted-foreground">
                    Embedding model
                  </dt>
                  <dd className="text-sm/6 text-foreground lg:col-span-2">
                    {fileData.embedding_model}
                  </dd>
                </div>
              )}
              {typeof fileData?.embedding_dimensions === "number" && (
                <div className="pb-2.5 lg:grid lg:grid-cols-3 lg:gap-4 lg:pb-0 lg:mb-2.5">
                  <dt className="text-sm/6 text-muted-foreground">
                    Dimensions
                  </dt>
                  <dd className="text-sm/6 text-foreground lg:col-span-2">
                    {fileData.embedding_dimensions}
                  </dd>
                </div>
              )}

              {/* Owner — wide view only (narrow shows it in the heading row) */}
              {fileData?.owner && (
                <div className="hidden lg:grid lg:grid-cols-3 lg:gap-4 lg:mb-2.5">
                  <dt className="text-sm/6 text-muted-foreground">Owned by</dt>
                  <dd className="text-sm/6 text-foreground lg:col-span-2">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900">
                        <span className="text-xs font-medium text-amber-800 dark:text-amber-200">
                          {String(fileData.owner).charAt(0).toUpperCase()}
                        </span>
                      </span>
                      <span className="text-sm break-all truncate">
                        {fileData.owner_name ||
                          fileData.owner_email ||
                          fileData.owner}
                      </span>
                    </div>
                  </dd>
                </div>
              )}
              {fileData?.allowed_users && fileData.allowed_users.length > 0 && (
                <div className="pb-2.5 lg:grid lg:grid-cols-3 lg:gap-4 lg:pb-0 lg:mb-2.5">
                  <dt className="text-sm/6 text-muted-foreground">
                    Allowed users
                  </dt>
                  <dd className="text-sm/6 text-foreground lg:col-span-2">
                    <div className="space-y-2">
                      {fileData.allowed_users.map((user, idx) => (
                        <div
                          key={user ?? idx}
                          className="flex items-center gap-2 overflow-hidden w-full"
                        >
                          <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-100 dark:bg-blue-900">
                            <span className="text-xs font-medium text-blue-800 dark:text-blue-200">
                              {user?.charAt(0).toUpperCase()}
                            </span>
                          </span>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span className="text-sm break-all truncate">
                                {user}
                              </span>
                            </TooltipTrigger>
                            <TooltipContent>{user}</TooltipContent>
                          </Tooltip>
                        </div>
                      ))}
                    </div>
                  </dd>
                </div>
              )}
              {fileData?.allowed_groups &&
                fileData.allowed_groups.length > 0 && (
                  <div className="pb-2.5 lg:grid lg:grid-cols-3 lg:gap-4 lg:pb-0 lg:mb-2.5">
                    <dt className="text-sm/6 text-muted-foreground">
                      Allowed groups
                    </dt>
                    <dd className="text-sm/6 text-foreground lg:col-span-2">
                      <div className="space-y-1">
                        {fileData.allowed_groups.map((group, idx) => (
                          <div
                            key={group ?? idx}
                            className="flex items-center gap-2"
                          >
                            <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-green-100 dark:bg-green-900">
                              <span className="text-xs font-medium text-green-800 dark:text-green-200">
                                {group?.charAt(0).toUpperCase()}
                              </span>
                            </span>
                            <span className="text-sm break-all">{group}</span>
                          </div>
                        ))}
                      </div>
                    </dd>
                  </div>
                )}
            </dl>
          </div>
        )}
      </div>
    </div>
  );
}

function ChunksPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center h-64">
          <div className="text-center">
            <Loader2 className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50 animate-spin" />
            <p className="text-lg text-muted-foreground">Loading...</p>
          </div>
        </div>
      }
    >
      <ChunksPageContent />
    </Suspense>
  );
}

export default function ProtectedChunksPage() {
  return (
    <ProtectedRoute>
      <ChunksPage />
    </ProtectedRoute>
  );
}
