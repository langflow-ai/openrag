"use client";

import { ArrowLeft, Check, Copy, Loader2, Search, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
// import { Label } from "@/components/ui/label";
// import { Checkbox } from "@/components/ui/checkbox";
import { ProtectedRoute } from "@/components/protected-route";
import { Button } from "@/components/ui/button";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import {
  type ChunkResult,
  type File,
  useGetSearchQuery,
} from "../../api/queries/useGetSearchQuery";
// import { Label } from "@/components/ui/label";
// import { Checkbox } from "@/components/ui/checkbox";
import { KnowledgeSearchInput } from "@/components/knowledge-search-input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const getFileTypeLabel = (mimetype: string) => {
  if (mimetype === "application/pdf") return "PDF";
  if (mimetype === "text/plain") return "Text";
  if (mimetype === "application/msword") return "Word Document";
  return "Unknown";
};

function ChunksPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { parsedFilterData, queryOverride } = useKnowledgeFilter();
  const filename = searchParams.get("filename");
  const [chunks, setChunks] = useState<ChunkResult[]>([]);
  // const [chunksFilteredByQuery, setChunksFilteredByQuery] = useState<
  //   ChunkResult[]
  // >([]);
  // const [selectedChunks, setSelectedChunks] = useState<Set<number>>(new Set());
  const [activeCopiedChunkIndex, setActiveCopiedChunkIndex] = useState<
    number | null
  >(null);

  // Calculate average chunk length
  const averageChunkLength = useMemo(
    () =>
      chunks.reduce((acc, chunk) => acc + chunk.text.length, 0) /
      chunks.length || 0,
    [chunks],
  );

  // const [selectAll, setSelectAll] = useState(false);

  // Use the same search query as the knowledge page, but we'll filter for the specific file
  const { data = [], isFetching } = useGetSearchQuery(
    queryOverride,
    parsedFilterData,
  );

  const handleCopy = useCallback((text: string, index: number) => {
    // Trim whitespace and remove new lines/tabs for cleaner copy
    navigator.clipboard.writeText(text.trim().replace(/[\n\r\t]/gm, ""));
    setActiveCopiedChunkIndex(index);
    setTimeout(() => setActiveCopiedChunkIndex(null), 10 * 1000); // 10 seconds
  }, []);

  const fileData = (data as File[]).find(
    (file: File) => file.filename === filename,
  );

  // Extract chunks for the specific file
  useEffect(() => {
    if (!filename || !(data as File[]).length) {
      setChunks([]);
      return;
    }

    setChunks(
      fileData?.chunks?.map((chunk, i) => ({ ...chunk, index: i + 1 })) || [],
    );
  }, [data, filename]);

  // Set selected state for all checkboxes when selectAll changes
  // useEffect(() => {
  //   if (selectAll) {
  //     setSelectedChunks(new Set(chunks.map((_, index) => index)));
  //   } else {
  //     setSelectedChunks(new Set());
  //   }
  // }, [selectAll, setSelectedChunks, chunks]);

  const handleBack = useCallback(() => {
    router.push("/knowledge");
  }, [router]);

  // const handleChunkCardCheckboxChange = useCallback(
  //   (index: number) => {
  //     setSelectedChunks((prevSelected) => {
  //       const newSelected = new Set(prevSelected);
  //       if (newSelected.has(index)) {
  //         newSelected.delete(index);
  //       } else {
  //         newSelected.add(index);
  //       }
  //       return newSelected;
  //     });
  //   },
  //   [setSelectedChunks]
  // );

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

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex flex-col mb-6">
        <div className="flex items-center gap-3 mb-6">
          <Button
            variant="ghost"
            onClick={handleBack}
            size="sm"
            className="max-w-8 max-h-8 -m-2"
          >
            <ArrowLeft size={24} />
          </Button>
          <h1 className="text-lg font-semibold">
            {/* Removes file extension from filename */}
            {filename.replace(/\.[^/.]+$/, "")}
          </h1>
        </div>
        <div className="flex flex-1">
          <KnowledgeSearchInput />
          {/* <div className="flex items-center pl-4 gap-2">
              <Checkbox
                id="selectAllChunks"
                checked={selectAll}
                onCheckedChange={handleSelectAll =>
                  setSelectAll(!!handleSelectAll)
                }
              />
              <Label
                htmlFor="selectAllChunks"
                className="font-medium text-muted-foreground whitespace-nowrap cursor-pointer"
              >
                Select all
              </Label>
            </div> */}
        </div>
      </div>

      <div className="grid gap-6 grid-cols-1 lg:grid-cols-[3fr_1fr]">
        {/* Content Area */}
        <div className="row-start-2 lg:row-start-1">
          {isFetching ? (
            <div className="flex items-center justify-center h-64">
              <div className="text-center">
                <Loader2 className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50 animate-spin" />
                <p className="text-lg text-muted-foreground">
                  Loading chunks...
                </p>
              </div>
            </div>
          ) : chunks.length === 0 ? (
            <div className="flex items-center justify-center h-64">
              <div className="text-center">
                <p className="text-xl font-semibold mb-2">No knowledge</p>
                <p className="text-sm text-secondary-foreground">
                  Clear the knowledge filter or return to the knowledge page
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-4 pb-6">
              {chunks.map((chunk, index) => (
                <div
                  key={chunk.filename + index}
                  className="bg-muted rounded-lg p-4 border border-border/50"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-3">
                      {/* <div>
                        <Checkbox
                          checked={selectedChunks.has(index)}
                          onCheckedChange={() =>
                            handleChunkCardCheckboxChange(index)
                          }
                        />
                      </div> */}
                      <span className="text-sm font-bold">
                        Chunk {chunk.index}
                      </span>
                      <span className="bg-background p-1 rounded text-xs text-muted-foreground/70">
                        {chunk.text.length} chars
                      </span>
                      <div className="py-1">
                        <Button
                          onClick={() => handleCopy(chunk.text, index)}
                          variant="ghost"
                          size="sm"
                        >
                          {activeCopiedChunkIndex === index ? (
                            <Check className="text-muted-foreground" />
                          ) : (
                            <Copy className="text-muted-foreground" />
                          )}
                        </Button>
                      </div>
                    </div>

                    <span className="bg-background p-1 rounded text-xs text-muted-foreground/70">
                      {chunk.score.toFixed(2)} score
                    </span>

                    {/* TODO: Update to use active toggle */}
                    {/* <span className="px-2 py-1 text-green-500">
                      <Switch
                        className="ml-2 bg-green-500"
                        checked={true}
                      />
                      Active
                    </span> */}
                  </div>
                  <blockquote className="text-sm text-muted-foreground leading-relaxed ml-1.5">
                    {chunk.text}
                  </blockquote>
                </div>
              ))}
            </div>
          )}
        </div>
        {/* Right panel - Summary (TODO), Technical details,  */}
        {chunks.length > 0 && (
          <div className="min-w-[200px]">
            <div className="mb-8">
              <h2 className="text-xl font-semibold mb-4">Technical details</h2>
              <dl>
                <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
                  <dt className="text-sm/6 text-muted-foreground">
                    Total chunks
                  </dt>
                  <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
                    {chunks.length}
                  </dd>
                </div>
                <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
                  <dt className="text-sm/6 text-muted-foreground">
                    Avg length
                  </dt>
                  <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
                    {averageChunkLength.toFixed(0)} chars
                  </dd>
                </div>
                {/* TODO: Uncomment after data is available */}
                {/* <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Process time</dt>
              <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
              </dd>
            </div>
            <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Model</dt>
              <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
              </dd>
            </div> */}
              </dl>
            </div>
            <div className="mb-4">
              <h2 className="text-xl font-semibold mt-2 mb-3">
                Original document
              </h2>
              <dl>
                {/* <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Name</dt>
              <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
                {fileData?.filename}
              </dd>
            </div> */}
                <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
                  <dt className="text-sm/6 text-muted-foreground">Type</dt>
                  <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
                    {fileData ? getFileTypeLabel(fileData.mimetype) : "Unknown"}
                  </dd>
                </div>
                <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
                  <dt className="text-sm/6 text-muted-foreground">Size</dt>
                  <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
                    {fileData?.size
                      ? `${Math.round(fileData.size / 1024)} KB`
                      : "Unknown"}
                  </dd>
                </div>
                {/* <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Uploaded</dt>
              <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
                N/A
              </dd>
            </div> */}
                {/* TODO: Uncomment after data is available */}
                {/* <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Source</dt>
              <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0"></dd>
            </div> */}
                {/* <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Updated</dt>
              <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
                N/A
              </dd>
            </div> */}
              </dl>
            </div>
            {(() => {
              const hasOwner = Boolean(fileData?.owner);
              const hasAllowedUsers = (fileData?.allowed_users?.length ?? 0) > 0;
              const hasAllowedGroups = (fileData?.allowed_groups?.length ?? 0) > 0;
              const showAccessControl =
                hasOwner || hasAllowedUsers || hasAllowedGroups;
              return showAccessControl;
            })() ? (
              <div className="mb-4">
                <h2 className="text-xl font-semibold mt-2 mb-3">
                  Access Control
                </h2>
                <dl>
                  {fileData?.owner && (
                    <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
                      <dt className="text-sm/6 text-muted-foreground">
                        Owner
                      </dt>
                      <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
                        <div className="flex items-center gap-2">
                          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900">
                            <span className="text-xs font-medium text-amber-800 dark:text-amber-200">
                              {String(fileData.owner).charAt(0).toUpperCase()}
                            </span>
                          </span>
                          <span className="text-sm break-all">
                            {fileData.owner_name || fileData.owner_email || fileData.owner}
                          </span>
                        </div>
                      </dd>
                    </div>
                  )}
                  {fileData?.allowed_users &&
                    fileData.allowed_users.length > 0 && (
                      <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
                        <dt className="text-sm/6 text-muted-foreground">
                          Allowed users
                        </dt>
                        <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
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
                                    <span className="text-sm break-all truncate">{user}</span>
                                  </TooltipTrigger>
                                  <TooltipContent>
                                    {user}
                                  </TooltipContent>
                                </Tooltip>
                              </div>
                            ))}
                          </div>
                        </dd>
                      </div>
                    )}

                  {fileData?.allowed_groups &&
                    fileData.allowed_groups.length > 0 && (
                      <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
                        <dt className="text-sm/6 text-muted-foreground">
                          Allowed groups
                        </dt>
                        <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
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
            ) : null}
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
