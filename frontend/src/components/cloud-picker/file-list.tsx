"use client";

import { Button } from "@/components/ui/button";
import { CloudFile } from "./types";
import { FileItem } from "./file-item";

interface FileListProps {
  provider: string;
  files: CloudFile[];
  onClearAll: () => void;
  onRemoveFile: (fileId: string) => void;
  shouldDisableActions: boolean;
}

export const FileList = ({
  provider,
  files,
  onClearAll,
  onRemoveFile,
  shouldDisableActions,
}: FileListProps) => {
  if (files.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2 relative">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">Selected items ({files.length})</p>
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
      <div className="box-shadow-inner">
        <div className="max-h-[calc(100vh-720px)] overflow-y-auto space-y-1 pr-1 pb-4 relative">
          {files.map((file) => (
            <FileItem
              key={file.id}
              file={file}
              onRemove={onRemoveFile}
              provider={provider}
              shouldDisableActions={shouldDisableActions}
            />
          ))}
        </div>
      </div>
    </div>
  );
};
