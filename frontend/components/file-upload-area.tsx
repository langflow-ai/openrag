"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";

interface FileUploadAreaProps {
  onFileSelected?: (file: File) => void;
  isLoading?: boolean;
  className?: string;
}

const FileUploadArea = React.forwardRef<HTMLDivElement, FileUploadAreaProps>(
  ({ onFileSelected, isLoading = false, className }, ref) => {
    const [isDragging, setIsDragging] = React.useState(false);
    const fileInputRef = React.useRef<HTMLInputElement>(null);

    const handleDragOver = (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(true);
    };

    const handleDragLeave = (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
    };

    const handleDrop = (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);

      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0 && onFileSelected) {
        onFileSelected(files[0]);
      }
    };

    const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      if (files.length > 0 && onFileSelected) {
        onFileSelected(files[0]);
      }
    };

    const handleClick = () => {
      if (!isLoading) {
        fileInputRef.current?.click();
      }
    };

    return (
      <div
        ref={ref}
        className={cn(
          "relative flex min-h-[150px] w-full cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-border bg-background p-6 text-center transition-colors hover:bg-muted/50",
          isDragging && "border-primary bg-primary/5",
          isLoading && "cursor-not-allowed opacity-50",
          className,
        )}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
      >
        <input
          ref={fileInputRef}
          type="file"
          onChange={handleFileSelect}
          className="hidden"
          disabled={isLoading}
        />

        <div className="flex flex-col items-center gap-4">
          {isLoading && (
            <div className="rounded-full bg-muted p-4">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          )}

          <div className="space-y-2">
            <h3 className="text-lg font-medium text-foreground">
              {isLoading
                ? "Processing file..."
                : "Drop files here or click to upload"}
            </h3>
            <p className="text-sm text-muted-foreground">
              {isLoading
                ? "Please wait while your file is being processed"
                : ""}
            </p>
          </div>

          {!isLoading && <Button size="sm">+ Upload</Button>}
        </div>
      </div>
    );
  },
);

FileUploadArea.displayName = "FileUploadArea";

export { FileUploadArea };
