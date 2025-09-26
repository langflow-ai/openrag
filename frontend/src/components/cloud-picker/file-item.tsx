"use client";

import { Badge } from "@/components/ui/badge";
import { FileText, Folder, Trash } from "lucide-react";
import { CloudFile } from "./types";

interface FileItemProps {
  file: CloudFile;
  onRemove: (fileId: string) => void;
}

const getFileIcon = (mimeType: string) => {
  if (mimeType.includes("folder")) {
    return <Folder className="h-6 w-6" />;
  }
  return <FileText className="h-6 w-6" />;
};

const getMimeTypeLabel = (mimeType: string) => {
  const typeMap: { [key: string]: string } = {
    "application/vnd.google-apps.document": "Google Doc",
    "application/vnd.google-apps.spreadsheet": "Google Sheet",
    "application/vnd.google-apps.presentation": "Google Slides",
    "application/vnd.google-apps.folder": "Folder",
    "application/pdf": "PDF",
    "text/plain": "Text",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
      "Word Doc",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation":
      "PowerPoint",
  };

  return typeMap[mimeType] || mimeType?.split("/").pop() || "Document";
};

const formatFileSize = (bytes?: number) => {
  if (!bytes) return "";
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  if (bytes === 0) return "0 B";
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${sizes[i]}`;
};

export const FileItem = ({ file, onRemove }: FileItemProps) => (
  <div
    key={file.id}
    className="flex items-center justify-between p-2 rounded-md text-xs"
  >
    <div className="flex items-center gap-2 flex-1 min-w-0">
      {getFileIcon(file.mimeType)}
      <span className="truncate font-medium text-sm mr-2">{file.name}</span>
      <Badge variant="secondary" className="text-xs px-1 py-0.5 h-auto">
        {getMimeTypeLabel(file.mimeType)}
      </Badge>
    </div>
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground mr-4" title="file size">
        {formatFileSize(file.size) || "—"}
      </span>

      <Trash
        className="text-muted-foreground w-5 h-5 cursor-pointer hover:text-destructive"
        onClick={() => onRemove(file.id)}
      />
    </div>
  </div>
);
