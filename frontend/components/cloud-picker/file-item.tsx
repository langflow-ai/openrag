"use client";

import { FileText, Folder, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getConnectorDescriptor } from "@/lib/connectors/registry";
import type { CloudFile } from "./types";

interface FileItemProps {
  provider: string;
  file: CloudFile;
  shouldDisableActions: boolean;
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
    "text/csv": "CSV",
    "text/html": "HTML",
    "application/xml": "XML",
    "application/json": "JSON",
    "application/msword": "Word Doc",
    "application/vnd.ms-excel": "Excel",
    "application/vnd.ms-powerpoint": "PowerPoint",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
      "Word Doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
      "Excel",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation":
      "PowerPoint",
    "application/octet-stream": "File",
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/gif": "GIF",
    "image/svg+xml": "SVG",
  };

  return typeMap[mimeType] || mimeType?.split("/").pop() || "Document";
};

const formatFileSize = (bytes?: number) => {
  if (!bytes) return "";
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  if (bytes === 0) return "0 B";
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / 1024 ** i).toFixed(1)} ${sizes[i]}`;
};

const getProviderIcon = (provider: string) => {
  const Icon = getConnectorDescriptor(provider)?.Icon;
  if (Icon) return <Icon />;
  return <FileText className="h-6 w-6" />;
};

export const FileItem = ({ file, onRemove, provider }: FileItemProps) => (
  <div
    key={file.id}
    className="flex items-center justify-between p-1.5 rounded-md text-xs"
  >
    <div className="flex items-center gap-2 flex-1 min-w-0">
      {file.isFolder ? (
        <Folder className="h-6 w-6" />
      ) : provider ? (
        getProviderIcon(provider)
      ) : (
        getFileIcon(file.mimeType)
      )}
      <span className="truncate font-medium text-sm mr-2">{file.name}</span>
      <span className="text-sm text-muted-foreground">
        {file.isFolder
          ? "Folder — all contents will be ingested"
          : getMimeTypeLabel(file.mimeType)}
      </span>
    </div>
    <div className="flex items-center gap-1">
      <span className="text-xs text-muted-foreground mr-4" title="file size">
        {formatFileSize(file.size) || "—"}
      </span>
      <Button
        className="text-muted-foreground  hover:text-destructive"
        size="icon"
        variant="ghost"
        onClick={() => onRemove(file.id)}
      >
        <Trash2 size={16} />
      </Button>
    </div>
  </div>
);
