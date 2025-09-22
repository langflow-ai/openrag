"use client";

import {
  ArrowLeft,
  Copy,
  File as FileIcon,
  Loader2,
  Search,
} from "lucide-react";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ProtectedRoute } from "@/components/protected-route";
import { Button } from "@/components/ui/button";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useTask } from "@/contexts/task-context";
import {
  type ChunkResult,
  type File,
  useGetSearchQuery,
} from "../../api/queries/useGetSearchQuery";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";

const getFileTypeLabel = (mimetype: string) => {
  if (mimetype === "application/pdf") return "PDF";
  if (mimetype === "text/plain") return "Text";
  if (mimetype === "application/msword") return "Word Document";
};

function ChunksPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isMenuOpen } = useTask();
  const { parsedFilterData, isPanelOpen } = useKnowledgeFilter();

  const filename = searchParams.get("filename");
  const [chunks, setChunks] = useState<ChunkResult[]>([]);
  const [chunksFilteredByQuery, setChunksFilteredByQuery] = useState<
    ChunkResult[]
  >([]);
  const averageChunkLength = useMemo(
    () =>
      chunks.reduce((acc, chunk) => acc + chunk.text.length, 0) /
        chunks.length || 0,
    [chunks]
  );

  const [selectAll, setSelectAll] = useState(false);
  const [queryInputText, setQueryInputText] = useState(
    parsedFilterData?.query ?? ""
  );

  // Use the same search query as the knowledge page, but we'll filter for the specific file
  const { data = [], isFetching } = useGetSearchQuery("*", parsedFilterData);

  useEffect(() => {
    if (queryInputText === "") {
      setChunksFilteredByQuery(chunks);
    } else {
      setChunksFilteredByQuery((prevChunks) =>
        prevChunks.filter((chunk) =>
          chunk.text.toLowerCase().includes(queryInputText.toLowerCase())
        )
      );
    }
  }, [queryInputText, chunks]);

  const handleCopy = useCallback((text: string) => {
    navigator.clipboard.writeText(text);
  }, []);

  const fileData = (data as File[]).find(
    (file: File) => file.filename === filename
  );

  // Extract chunks for the specific file
  useEffect(() => {
    if (!filename || !(data as File[]).length) {
      setChunks([]);
      return;
    }

    setChunks(fileData?.chunks || []);
  }, [data, filename, fileData?.chunks]);

  const handleBack = useCallback(() => {
    router.back();
  }, [router]);

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
      className={`fixed inset-0 md:left-72 top-[53px] flex flex-row transition-all duration-300 ${
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
    >
      <div className="flex-1 flex flex-col min-h-0 px-6 py-6">
        {/* Header */}
        <div className="flex flex-col mb-6">
          <div className="flex items-center gap-3 mb-2">
            <Button variant="ghost" onClick={handleBack}>
              <ArrowLeft size={18} />
              <FileIcon className="text-muted-foreground" size={18} />
              <h1 className="text-lg font-semibold">
                {filename.replace(/\.[^/.]+$/, "")}
              </h1>
            </Button>
          </div>
          <div className="flex items-center gap-3 pl-4 mt-2">
            <div className="flex items-center gap-2">
              <Checkbox
                id="selectAllChunks"
                checked={selectAll}
                onCheckedChange={(checked) => setSelectAll(checked === true)}
              />
              <Label
                htmlFor="selectAllChunks"
                className="font-medium text-muted-foreground whitespace-nowrap"
              >
                Select all
              </Label>
            </div>
            <div className="flex-1 flex items-center gap-2">
              <Input
                name="search-query"
                id="search-query"
                type="text"
                defaultValue={parsedFilterData?.query}
                value={queryInputText}
                onChange={(e) => setQueryInputText(e.target.value)}
                placeholder="Search chunks..."
                className="flex-1 bg-muted/20 rounded-lg border border-border/50 px-4 py-3 focus-visible:ring-1 focus-visible:ring-ring"
              />
              <Button variant="outline" size="sm">
                <Search />
              </Button>
            </div>
          </div>
        </div>

        {/* Content Area - matches knowledge page structure */}
        <div className="flex-1 overflow-auto">
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
                        <Checkbox />
                      </div>
                      <span className="text-sm text-bold">
                        Chunk {chunk.page}
                      </span>
                      <span className="bg-background p-1 rounded text-xs text-muted-foreground/70">
                        {chunk.text.length} chars
                      </span>
                      <div className="py-1">
                        <Button
                          className="p-1"
                          onClick={() => handleCopy(chunk.text)}
                          variant="ghost"
                          size="xs"
                        >
                          <Copy className="text-muted-foreground" />
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
                  <div>
                    <blockquote className="text-sm text-muted-foreground leading-relaxed border-l-2 border-color-input ml-1.5 pl-4">
                      {chunk.text}
                    </blockquote>
                  </div>
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
            <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Process time</dt>
              <dd className="mt-1 text-sm/6 text-gray-100 sm:col-span-2 sm:mt-0">
                {/* {averageChunkLength.toFixed(0)} chars */}
              </dd>
            </div>
            <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Model</dt>
              <dd className="mt-1 text-sm/6 text-gray-100 sm:col-span-2 sm:mt-0">
                {/* {averageChunkLength.toFixed(0)} chars */}
              </dd>
            </div>
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
            <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
              <dt className="text-sm/6 text-muted-foreground">Source</dt>
              <dd className="mt-1 text-sm/6 text-gray-100 sm:col-span-2 sm:mt-0"></dd>
            </div>
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
