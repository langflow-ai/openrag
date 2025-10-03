"use client";

import { Button } from "@/components/ui/button";
import { CloudFile } from "./types";
import { FileItem } from "./file-item";

interface FileListProps {
  provider: string;
  files: CloudFile[];
  onClearAll: () => void;
  onRemoveFile: (fileId: string) => void;
}

export const FileList = ({
  provider,
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
        <p className="text-sm font-medium">Added files ({files.length})</p>
        <Button
          ignoreTitleCase={true}
          onClick={onClearAll}
          size="sm"
          variant="ghost"
          className="text-sm text-muted-foreground"
        >
          Remove all
        </Button>
      </div>
      <div className="max-h-64 overflow-y-auto space-y-1">
        {files.map((file) => (
          <FileItem
            key={file.id}
            file={file}
            onRemove={onRemoveFile}
            provider={provider}
          />
        ))}
      </div>
    </div>
  );
};
