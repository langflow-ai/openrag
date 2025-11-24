import { Loader2, X } from "lucide-react";
import Image from "next/image";
import { Button } from "@/components/ui/button";

interface FilePreviewProps {
  uploadedFile: File;
  onClear: () => void;
  isUploading?: boolean;
}

const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + " " + sizes[i];
};

const getFilePreviewUrl = (file: File): string => {
  if (file.type.startsWith("image/")) {
    return URL.createObjectURL(file);
  }
  return "";
};

export const FilePreview = ({ uploadedFile, onClear, isUploading = false }: FilePreviewProps) => {
  return (
    <div className="max-w-[250px] flex items-center gap-2 p-2 bg-muted rounded-lg">
      {/* File Image Preview */}
      <div className="flex-shrink-0 w-8 h-8 bg-background rounded border border-input flex items-center justify-center overflow-hidden">
        {isUploading ? (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        ) : getFilePreviewUrl(uploadedFile) ? (
          <Image
            src={getFilePreviewUrl(uploadedFile)}
            alt="File preview"
            width={32}
            height={32}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="text-xs font-medium text-muted-foreground">
            {uploadedFile.name.split(".").pop()?.toUpperCase()}
          </div>
        )}
      </div>

      {/* File Info */}
      <div className="flex-1 min-w-0">
        <div className="text-xs text-muted-foreground font-medium truncate">
          {uploadedFile.name}
        </div>
        <div className="text-xxs text-muted-foreground">
          {formatFileSize(uploadedFile.size)}
        </div>
      </div>

      {/* Clear Button */}
      <Button
        type="button"
        variant="ghost"
        size="iconSm"
        onClick={onClear}
        className="flex-shrink-0 h-8 w-8 p-0 rounded-md hover:bg-background/50"
      >
        <X className="h-4 w-4" />
      </Button>
    </div>
  );
};
