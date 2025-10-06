"use client";

import { ArrowLeft, Check, Copy, Loader2, Search } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { ProtectedRoute } from "@/components/protected-route";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useLayout } from "@/contexts/layout-context";
import { useTask } from "@/contexts/task-context";
import {
  type ChunkResult,
  type File,
  useGetSearchQuery,
} from "../../api/queries/useGetSearchQuery";

const getFileTypeLabel = (mimetype: string) => {
  if (mimetype === "application/pdf") return "PDF";
  if (mimetype === "text/plain") return "Text";
  if (mimetype === "application/msword") return "Word Document";
  return "Unknown";
};

function ChunksPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isMenuOpen } = useTask();
  const { totalTopOffset } = useLayout();
  const { parsedFilterData, isPanelOpen } = useKnowledgeFilter();

  const filename = searchParams.get("filename");
  const [chunks, setChunks] = useState<ChunkResult[]>([]);
  const [chunksFilteredByQuery, setChunksFilteredByQuery] = useState<
    ChunkResult[]
  >([]);
  const [selectedChunks, setSelectedChunks] = useState<Set<number>>(new Set());
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

  const [selectAll, setSelectAll] = useState(false);
  const [queryInputText, setQueryInputText] = useState(
    parsedFilterData?.query ?? "",
  );

  // Use the same search query as the knowledge page, but we'll filter for the specific file
  const { data = [], isFetching } = useGetSearchQuery("*", parsedFilterData);

  useEffect(() => {
    if (queryInputText === "") {
      setChunksFilteredByQuery(chunks);
    } else {
      setChunksFilteredByQuery(
        chunks.filter((chunk) =>
          chunk.text.toLowerCase().includes(queryInputText.toLowerCase()),
        ),
      );
    }
  }, [queryInputText, chunks]);

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

    setChunks(fileData?.chunks || []);
  }, [data, filename]);

  // Set selected state for all checkboxes when selectAll changes
  useEffect(() => {
    if (selectAll) {
      setSelectedChunks(new Set(chunks.map((_, index) => index)));
    } else {
      setSelectedChunks(new Set());
    }
  }, [selectAll, setSelectedChunks, chunks]);

  const handleBack = useCallback(() => {
    router.push("/knowledge");
  }, [router]);

  const handleChunkCardCheckboxChange = useCallback(
    (index: number) => {
      setSelectedChunks((prevSelected) => {
        const newSelected = new Set(prevSelected);
        if (newSelected.has(index)) {
          newSelected.delete(index);
        } else {
          newSelected.add(index);
        }
        return newSelected;
      });
    },
    [setSelectedChunks],
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

  return (
    <div
      className={`fixed inset-0 md:left-72 flex flex-row transition-all duration-300 ${
        isMenuOpen && isPanelOpen
          ? "md:right-[704px]"
          : // Both open: 384px (menu) + 320px (KF panel)
          isMenuOpen
          ? "md:right-96"
          : // Only menu open: 384px
          isPanelOpen
          ? "md:right-80"
          : // Only KF panel open: 320px
            "md:right-6" // Neither open: 24px
      }`}
      style={{ top: `${totalTopOffset}px` }}
    >
      <div className="flex-1 flex flex-col min-h-0 px-6 py-6">
        {/* Header */}
        <div className="flex flex-col mb-6">
          <div className="flex flex-row items-center gap-3 mb-6">
            <Button variant="ghost" onClick={handleBack} size="sm">
              <ArrowLeft size={24} />
            </Button>
            <h1 className="text-lg font-semibold">
              {/* Removes file extension from filename */}
              {filename.replace(/\.[^/.]+$/, "")}
            </h1>
          </div>
          <div className="flex flex-col items-start mt-2">
            <div className="flex-1 flex items-center gap-2 w-full max-w-[616px] mb-8">
              <Input
                name="search-query"
                icon={
                  !queryInputText.length ? <Search className="h-4 w-4" /> : null
                }
                id="search-query"
                type="text"
                defaultValue={parsedFilterData?.query}
                value={queryInputText}
                onChange={(e) => setQueryInputText(e.target.value)}
                placeholder="Search chunks..."
              />
            </div>
            <div className="flex items-center pl-4 gap-2">
              <Checkbox
                id="selectAllChunks"
                checked={selectAll}
                onCheckedChange={(handleSelectAll) =>
                  setSelectAll(!!handleSelectAll)
                }
              />
              <Label
                htmlFor="selectAllChunks"
                className="font-medium text-muted-foreground whitespace-nowrap cursor-pointer"
              >
                Select all
              </Label>
            </div>
          </div>
        </div>

        {/* Content Area - matches knowledge page structure */}
        <div className="flex-1 overflow-scroll pr-6">
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
                <Search className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                <p className="text-lg text-muted-foreground">No chunks found</p>
                <p className="text-sm text-muted-foreground/70 mt-2">
                  This file may not have been indexed yet
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-4 pb-6">
              {chunksFilteredByQuery.map((chunk, index) => (
                <div
                  key={chunk.filename + index}
                  className="bg-muted rounded-lg p-4 border border-border/50"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-3">
                      <div>
                        <Checkbox
                          checked={selectedChunks.has(index)}
                          onCheckedChange={() =>
                            handleChunkCardCheckboxChange(index)
                          }
                        />
                      </div>
                      <span className="text-sm font-bold">
                        Chunk {chunk.page}
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

                    {/* TODO: Update to use active toggle */}
                    {/* <span className="px-2 py-1 text-green-500">
                      <Switch
                        className="ml-2 bg-green-500"
                        checked={true}
                      />
                      Active
                    </span> */}
                  </div>
                  <blockquote className="text-sm text-muted-foreground leading-relaxed border-l-2 border-input ml-1.5 pl-4">
                    {chunk.text}
                  </blockquote>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      {/* Right panel - Summary (TODO), Technical details,  */}
      <div className="w-[320px] py-20 px-2">
        <div className="mb-8">
          <h2 className="text-xl font-semibold mt-3 mb-4">Technical details</h2>
          <dl>
            <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Total chunks</dt>
              <dd className="mt-1 text-sm/6 text-gray-100 sm:col-span-2 sm:mt-0">
                {chunks.length}
              </dd>
            </div>
            <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Avg length</dt>
              <dd className="mt-1 text-sm/6 text-gray-100 sm:col-span-2 sm:mt-0">
                {averageChunkLength.toFixed(0)} chars
              </dd>
            </div>
            {/* TODO: Uncomment after data is available */}
            {/* <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Process time</dt>
              <dd className="mt-1 text-sm/6 text-gray-100 sm:col-span-2 sm:mt-0">
              </dd>
            </div>
            <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Model</dt>
              <dd className="mt-1 text-sm/6 text-gray-100 sm:col-span-2 sm:mt-0">
              </dd>
            </div> */}
          </dl>
        </div>
        <div className="mb-8">
          <h2 className="text-xl font-semibold mt-2 mb-3">Original document</h2>
          <dl>
            <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Name</dt>
              <dd className="mt-1 text-sm/6 text-gray-100 sm:col-span-2 sm:mt-0">
                {fileData?.filename}
              </dd>
            </div>
            <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Type</dt>
              <dd className="mt-1 text-sm/6 text-gray-100 sm:col-span-2 sm:mt-0">
                {fileData ? getFileTypeLabel(fileData.mimetype) : "Unknown"}
              </dd>
            </div>
            <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Size</dt>
              <dd className="mt-1 text-sm/6 text-gray-100 sm:col-span-2 sm:mt-0">
                {fileData?.size
                  ? `${Math.round(fileData.size / 1024)} KB`
                  : "Unknown"}
              </dd>
            </div>
            <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Uploaded</dt>
              <dd className="mt-1 text-sm/6 text-gray-100 sm:col-span-2 sm:mt-0">
                N/A
              </dd>
            </div>
            {/* TODO: Uncomment after data is available */}
            {/* <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Source</dt>
              <dd className="mt-1 text-sm/6 text-gray-100 sm:col-span-2 sm:mt-0"></dd>
            </div> */}
            <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Updated</dt>
              <dd className="mt-1 text-sm/6 text-gray-100 sm:col-span-2 sm:mt-0">
                N/A
              </dd>
            </div>
          </dl>
        </div>
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
