"use client";

import { Button } from "@/components/ui/button";
import { CloudFile } from "./types";
import { FileItem } from "./file-item";

interface FileListProps {
  files: CloudFile[];
  onClearAll: () => void;
  onRemoveFile: (fileId: string) => void;
}

export const FileList = ({
  files,
  onClearAll,
  onRemoveFile,
}: FileListProps) => {
  if (files.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">Added files</p>
        <Button
          onClick={onClearAll}
          size="sm"
          variant="ghost"
          className="text-sm text-muted-foreground"
        >
          Clear all
        </Button>
      </div>
      <div className="max-h-64 overflow-y-auto space-y-1">
        {files.map(file => (
          <FileItem key={file.id} file={file} onRemove={onRemoveFile} />
        ))}
      </div>
    </div>
  );
};
