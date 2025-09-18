"use client";

import {
  Building2,
  Cloud,
  FileText,
  HardDrive,
  Loader2,
  Search,
} from "lucide-react";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SiGoogledrive } from "react-icons/si";
import { TbBrandOnedrive } from "react-icons/tb";
import { ProtectedRoute } from "@/components/protected-route";
import { Button } from "@/components/ui/button";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useTask } from "@/contexts/task-context";
import {
  type ChunkResult,
  type File,
  useGetSearchQuery,
} from "../../api/queries/useGetSearchQuery";

// Function to get the appropriate icon for a connector type
function getSourceIcon(connectorType?: string) {
  switch (connectorType) {
    case "google_drive":
      return <SiGoogledrive className="h-4 w-4 text-foreground" />;
    case "onedrive":
      return <TbBrandOnedrive className="h-4 w-4 text-foreground" />;
    case "sharepoint":
      return <Building2 className="h-4 w-4 text-foreground" />;
    case "s3":
      return <Cloud className="h-4 w-4 text-foreground" />;
    default:
      return <HardDrive className="h-4 w-4 text-muted-foreground" />;
  }
}

function ChunksPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isMenuOpen } = useTask();
  const { parsedFilterData, isPanelOpen } = useKnowledgeFilter();

  const filename = searchParams.get("filename");
  const [chunks, setChunks] = useState<ChunkResult[]>([]);

  // Use the same search query as the knowledge page, but we'll filter for the specific file
  const { data = [], isFetching } = useGetSearchQuery("*", parsedFilterData);

  // Extract chunks for the specific file
  useEffect(() => {
    if (!filename || !(data as File[]).length) {
      setChunks([]);
      return;
    }

    const fileData = (data as File[]).find(
      (file: File) => file.filename === filename
    );
    setChunks(fileData?.chunks || []);
  }, [data, filename]);

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
      className={`fixed inset-0 md:left-72 top-[53px] flex flex-col transition-all duration-300 ${
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
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleBack}
              className="text-muted-foreground hover:text-foreground px-2"
            >
              ← Back
            </Button>
            <div className="flex flex-col">
              <h2 className="text-lg font-semibold">Document Chunks</h2>
              <p className="text-sm text-muted-foreground truncate max-w-md">
                {decodeURIComponent(filename)}
              </p>
            </div>
          </div>
          <div className="text-sm text-muted-foreground">
            {!isFetching && chunks.length > 0 && (
              <span>
                {chunks.length} chunk{chunks.length !== 1 ? "s" : ""} found
              </span>
            )}
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
              {chunks.map((chunk, index) => (
                <div
                  key={chunk.filename + index}
                  className="bg-muted/20 rounded-lg p-4 border border-border/50"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-blue-400" />
                      <span className="font-medium truncate">
                        {chunk.filename}
                      </span>
                      {chunk.connector_type && (
                        <div className="ml-2">
                          {getSourceIcon(chunk.connector_type)}
                        </div>
                      )}
                    </div>
                    <span className="text-xs text-green-400 bg-green-400/20 px-2 py-1 rounded">
                      {chunk.score.toFixed(2)}
                    </span>
                  </div>
                  <div className="flex items-center gap-4 text-sm text-muted-foreground mb-3">
                    <span>{chunk.mimetype}</span>
                    <span>Page {chunk.page}</span>
                    {chunk.owner_name && <span>Owner: {chunk.owner_name}</span>}
                  </div>
                  <p className="text-sm text-foreground/90 leading-relaxed">
                    {chunk.text}
                  </p>
                </div>
              ))}
            </div>
          )}
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
