"use client";

import { Download, Search } from "lucide-react";
import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  getDownloadSourceUrl,
  getPreviewSourceUrl,
  type SourcePreviewKind,
} from "@/lib/source-url";
import { Button } from "./ui/button";

interface SourcePreviewDialogProps {
  filename: string;
  kind: SourcePreviewKind;
  mimetype?: string;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  referencePage?: number;
  sourceUrl: string;
}

/** Display a safe source preview without leaving the current page. */
export function SourcePreviewDialog({
  filename,
  kind,
  mimetype,
  onOpenChange,
  open,
  referencePage,
  sourceUrl,
}: SourcePreviewDialogProps) {
  const [previewKey, setPreviewKey] = useState(0);
  const normalizedMimetype = mimetype?.split(";", 1)[0].trim().toLowerCase();
  const pdfReferencePage =
    (normalizedMimetype === "application/pdf" ||
      filename.toLowerCase().endsWith(".pdf")) &&
    referencePage &&
    referencePage > 0
      ? referencePage
      : undefined;
  const previewUrl = getPreviewSourceUrl(sourceUrl, pdfReferencePage);
  const downloadUrl = getDownloadSourceUrl(sourceUrl);

  if (!previewUrl || !downloadUrl) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[85vh] w-[95vw] max-w-5xl flex-col">
        <DialogHeader>
          <DialogTitle className="truncate pr-8">{filename}</DialogTitle>
          <DialogDescription>Original document preview</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden rounded-md border bg-muted/30">
          {kind === "image" ? (
            // biome-ignore lint/performance/noImgElement: authenticated source URLs are not supported by next/image.
            <img
              src={previewUrl}
              alt={`Preview of ${filename}`}
              className="max-h-full max-w-full object-contain"
            />
          ) : (
            <iframe
              key={previewKey}
              sandbox=""
              referrerPolicy="no-referrer"
              src={previewUrl}
              title={`Preview of ${filename}`}
              className="h-full w-full bg-white"
            />
          )}
        </div>

        <DialogFooter>
          {kind === "document" && pdfReferencePage && (
            <Button
              type="button"
              variant="outline"
              onClick={() => setPreviewKey((key) => key + 1)}
            >
              <Search className="mr-2 h-4 w-4" />
              Find reference (page {pdfReferencePage})
            </Button>
          )}
          <Button asChild variant="outline">
            <a
              href={downloadUrl}
              download={filename}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Download className="mr-2 h-4 w-4" />
              Download original
            </a>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
