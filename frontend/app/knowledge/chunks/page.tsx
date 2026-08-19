"use client";

import { ArrowLeft, Download, Eye, Loader2, Search } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useFileScopedChunksQuery } from "@/app/api/queries/useFileScopedChunksQuery";
import { FileChunksPanel } from "@/components/file-chunks-panel";
import { ProtectedRoute } from "@/components/protected-route";
import { SourcePreviewDialog } from "@/components/source-preview-dialog";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { formatFileSize, getFileTypeLabel } from "@/lib/file-format";
import { getDownloadSourceUrl, getSourcePreviewKind } from "@/lib/source-url";

function ChunksPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const filename = searchParams.get("filename");
  const [previewOpen, setPreviewOpen] = useState(false);
  const { file: fileData } = useFileScopedChunksQuery(filename);

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
  const downloadSourceUrl = getDownloadSourceUrl(fileData?.source_url);
  const previewKind = getSourcePreviewKind(filename, fileData?.mimetype);
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
          <FileChunksPanel filename={filename} />
        </div>

        {chunkCount > 0 && (
          <div className="min-w-[200px]">
            <div className="mb-8">
              <h2 className="text-xl font-semibold mb-4">Technical details</h2>
              <dl>
                <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
                  <dt className="text-sm/6 text-muted-foreground">
                    Total chunks
                  </dt>
                  <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
                    {chunkCount}
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
              </dl>
            </div>
            <div className="mb-4">
              <h2 className="text-xl font-semibold mt-2 mb-3">
                Original document
              </h2>
              <dl>
                <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
                  <dt className="text-sm/6 text-muted-foreground">Type</dt>
                  <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
                    {fileData ? getFileTypeLabel(fileData.mimetype) : "Unknown"}
                  </dd>
                </div>
                <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
                  <dt className="text-sm/6 text-muted-foreground">Size</dt>
                  <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
                    {fileData?.size ? formatFileSize(fileData.size) : "Unknown"}
                  </dd>
                </div>
              </dl>
              {downloadSourceUrl && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {previewKind && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setPreviewOpen(true)}
                    >
                      <Eye className="h-4 w-4 mr-2" />
                      Preview
                    </Button>
                  )}
                  <Button asChild variant="outline" size="sm">
                    <a
                      href={downloadSourceUrl}
                      download={filename}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <Download className="h-4 w-4 mr-2" />
                      Download original
                    </a>
                  </Button>
                </div>
              )}
              {downloadSourceUrl && previewKind && (
                <SourcePreviewDialog
                  filename={filename}
                  kind={previewKind}
                  open={previewOpen}
                  onOpenChange={setPreviewOpen}
                  sourceUrl={downloadSourceUrl}
                />
              )}
            </div>
            {hasAccessControl && (
              <div className="mb-4">
                <h2 className="text-xl font-semibold mt-2 mb-3">
                  Access Control
                </h2>
                <dl>
                  {fileData?.owner && (
                    <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:px-0 mb-2.5">
                      <dt className="text-sm/6 text-muted-foreground">Owner</dt>
                      <dd className="mt-1 text-sm/6 text-gray-800 dark:text-gray-100 sm:col-span-2 sm:mt-0">
                        <div className="flex items-center gap-2">
                          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900">
                            <span className="text-xs font-medium text-amber-800 dark:text-amber-200">
                              {String(fileData.owner).charAt(0).toUpperCase()}
                            </span>
                          </span>
                          <span className="text-sm break-all">
                            {fileData.owner_name ||
                              fileData.owner_email ||
                              fileData.owner}
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
                                <span className="text-sm break-all">
                                  {group}
                                </span>
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
